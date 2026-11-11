"""Categorização por LLM em segundo plano.

Numa CPU sem GPU, um modelo local leva alguns segundos por estabelecimento. Em vez de prender a
importação, ela responde na hora com memória e regras, e este job manda as pendentes para a LLM
depois. Um lock garante um job por vez; se novas pendentes chegarem durante a execução, o job
roda de novo ao terminar.

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
from app.tenancy import user_session

logger = logging.getLogger(__name__)


@dataclass
class JobStatus:
    running: bool
    pending: int
    last_categorized: int
    last_error: str | None


class CategorizationJob:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rerun = False
        self.running = False
        self.last_categorized = 0
        self.last_error: str | None = None

    def run(self, provider: LLMProvider | None, batch_size: int) -> None:
        if provider is None:
            return
        if not self._lock.acquire(blocking=False):
            self._rerun = True  # já tem um job rodando: ele pega as novas pendentes no fim
            return
        try:
            self.running = True
            self.last_categorized, self.last_error = 0, None
            while True:
                self._rerun = False
                # Uma rodada por dono: a memória e as categorias usadas são as de cada usuário.
                for owner in self._owners_with_pending():
                    with user_session(owner) as db:
                        pending = db.scalars(
                            select(Transaction).where(
                                Transaction.categorized_by == CategorizedBy.none
                            )
                        ).all()
                        outcome = categorize_transactions(db, pending, provider, batch_size)
                        db.commit()
                        self.last_categorized += outcome.stats.llm
                        self.last_error = outcome.llm_error
                    if self.last_error:
                        break
                if not self._rerun or self.last_error:
                    break
        except Exception:
            logger.exception("Falha no job de categorização")
            self.last_error = "Erro inesperado ao categorizar em segundo plano."
        finally:
            self.running = False
            self._lock.release()

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
        """`db` é a sessão do usuário logado: as pendentes contadas são só as dele."""
        pending = db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.categorized_by == CategorizedBy.none
            )
        )
        return JobStatus(self.running, pending or 0, self.last_categorized, self.last_error)


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
