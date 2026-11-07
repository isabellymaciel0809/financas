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

from app.config import get_settings
from app.database import SessionLocal
from app.models import CategorizedBy, Transaction
from app.services.categorizer.llm import LLMProvider
from app.services.categorizer.pipeline import categorize_transactions

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
                with SessionLocal() as db:
                    pending = db.scalars(
                        select(Transaction).where(Transaction.categorized_by == CategorizedBy.none)
                    ).all()
                    if pending:
                        outcome = categorize_transactions(db, pending, provider, batch_size)
                        db.commit()
                        self.last_categorized += outcome.stats.llm
                        self.last_error = outcome.llm_error
                if not self._rerun or self.last_error:
                    break
        except Exception:
            logger.exception("Falha no job de categorização")
            self.last_error = "Erro inesperado ao categorizar em segundo plano."
        finally:
            self.running = False
            self._lock.release()

    def status(self) -> JobStatus:
        with SessionLocal() as db:
            pending = db.scalar(
                select(func.count()).where(Transaction.categorized_by == CategorizedBy.none)
            )
        return JobStatus(self.running, pending or 0, self.last_categorized, self.last_error)


categorization_job = CategorizationJob()


def queue_llm(background: BackgroundTasks, provider: LLMProvider | None, pending: int) -> int:
    """Agenda a LLM para as pendentes, se houver pendentes e uma LLM acessível."""
    if pending == 0 or provider is None or not provider.is_available():
        return 0
    background.add_task(categorization_job.run, provider, get_settings().llm_batch_size)
    return pending
