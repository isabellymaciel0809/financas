"""Categorização por LLM em segundo plano.

Numa CPU sem GPU, um modelo local leva alguns segundos por estabelecimento. Em vez de prender a
importação, ela responde na hora com memória e regras, e este job manda as pendentes para a LLM
depois. Um job por vez (app/services/serial.py); se novas pendentes chegarem durante a
execução, o job roda de novo ao terminar.

Limitação consciente: o estado fica em memória, então vale para um único processo do servidor
(o caso deste app). Com vários workers, o caminho seria uma fila (ex.: Redis + RQ/Celery).
"""

import logging
import threading
from dataclasses import dataclass

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import CategorizedBy, Expense, ExpenseStatus, Transaction
from app.services.categorizer.llm import LLMProvider
from app.services.categorizer.pipeline import categorize_transactions
from app.services.fiscal.processor import expense_queue
from app.services.serial import SerialRunner
from app.tenancy import current_user_id, user_session

logger = logging.getLogger(__name__)


@dataclass
class JobStatus:
    running: bool
    pending: int
    last_categorized: int
    last_error: str | None


@dataclass
class LastRun:
    """O que a última execução fez com as transações de um usuário."""

    categorized: int = 0
    error: str | None = None


class CategorizationJob:
    def __init__(self) -> None:
        self._runner = SerialRunner()
        # Por dono: cada um vê quantas das *suas* transações a IA categorizou, não as dos outros.
        self._results: dict[int | None, LastRun] = {}

    def run(self, provider: LLMProvider | None, batch_size: int) -> None:
        if provider is None:
            return
        seen: set[int | None] = set()  # donos já atendidos nesta execução (soma as rodadas)
        self._runner.trigger(lambda: self._round(provider, batch_size, seen))

    def _round(self, provider: LLMProvider, batch_size: int, seen: set[int | None]) -> bool:
        # Uma passada por dono: a memória e as categorias usadas são as de cada usuário.
        for owner in self._owners_with_pending():
            try:
                with user_session(owner) as db:
                    pending = db.scalars(
                        select(Transaction).where(Transaction.categorized_by == CategorizedBy.none)
                    ).all()
                    outcome = categorize_transactions(db, pending, provider, batch_size)
                    before = self._results[owner].categorized if owner in seen else 0
                    seen.add(owner)
                    # Antes do commit: quando a tela vir as pendentes zerarem, o total já está aqui.
                    self._results[owner] = LastRun(before + outcome.stats.llm, outcome.llm_error)
                    db.commit()
            except Exception:
                logger.exception("Falha no job de categorização")
                self._results[owner] = LastRun(
                    error="Erro inesperado ao categorizar em segundo plano."
                )
                return False
            if outcome.llm_error:
                return False  # LLM fora do ar: os outros donos também falhariam
        return True

    @staticmethod
    def _owners_with_pending() -> list[int | None]:
        with SessionLocal() as db:  # sem dono: enxerga todos, só para saber quem tem pendentes
            return list(
                db.scalars(
                    select(Transaction.user_id)
                    .where(Transaction.categorized_by == CategorizedBy.none)
                    .distinct()
                )
            )

    def status(self, db: Session) -> JobStatus:
        """Situação do usuário logado (`db` é a sessão dele): só as pendentes e o resultado dele.

        "Rodando" só para quem tem pendentes: senão a tela de quem não importou nada veria o job
        de outra pessoa terminar e avisaria "IA categorizou" com um resultado antigo.
        """
        pending = (
            db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.categorized_by == CategorizedBy.none
                )
            )
            or 0
        )
        last = self._results.get(current_user_id(db), LastRun())
        running = self._runner.running and pending > 0
        return JobStatus(running, pending, last.categorized, last.error)

    def reset(self) -> None:
        """Esquece os resultados (os testes começam do zero, como o `login_limiter`)."""
        self._results.clear()


categorization_job = CategorizationJob()


def queue_llm(background: BackgroundTasks, provider: LLMProvider | None, pending: int) -> int:
    """Agenda a LLM para as pendentes, se houver pendentes e uma LLM acessível."""
    if pending == 0 or provider is None or not provider.is_available():
        return 0
    background.add_task(categorization_job.run, provider, get_settings().llm_batch_size)
    return pending


def resume_pending_work(provider: LLMProvider | None) -> None:
    """Retoma o que ficou pela metade quando o servidor parou.

    As filas só eram disparadas por um envio novo. Se o servidor reiniciasse com notas em
    "Processando" ou transações esperando a LLM, elas ficavam paradas até alguém enviar outro
    arquivo. O estado das filas está no banco (status e `categorized_by`), então basta rodá-las
    de novo ao iniciar.
    """
    try:
        with SessionLocal() as db:  # sem dono: conta de todos os usuários
            files = db.scalar(  # mesmo filtro da fila: só o que tem arquivo para ler
                select(func.count(Expense.id)).where(
                    Expense.status == ExpenseStatus.processing,
                    Expense.stored_filename.is_not(None),
                )
            )
            pending = db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.categorized_by == CategorizedBy.none
                )
            )
        if files:
            logger.info("Retomando a leitura de %s arquivo(s) que ficaram na fila.", files)
            expense_queue.run(provider)
        # Depois dos arquivos: a LLM e o OCR disputam a mesma CPU.
        if pending and provider is not None and provider.is_available():
            logger.info("Retomando a categorização de %s transação(ões) pela LLM.", pending)
            categorization_job.run(provider, get_settings().llm_batch_size)
    except Exception:
        logger.exception("Falha ao retomar as filas em segundo plano")


def resume_in_background(provider: LLMProvider | None) -> threading.Thread:
    """Roda `resume_pending_work` numa thread: ler fotos leva minutos e não pode travar o início."""
    thread = threading.Thread(
        target=resume_pending_work, args=(provider,), name="retomar-filas", daemon=True
    )
    thread.start()
    return thread
