"""Transforma um arquivo enviado (XML ou foto) em lançamento validado.

O processamento roda numa fila em segundo plano: numa CPU sem GPU, ler uma foto (OCR + LLM)
leva minutos, e quem envia não precisa esperar na tela.
"""

import logging
import threading
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Expense, ExpenseItem, ExpenseSource, ExpenseStatus, Supplier
from app.services.categorizer.llm import LLMProvider
from app.services.fiscal.extracted import ExtractedDocument
from app.services.fiscal.items import categorize_items
from app.services.fiscal.keys import only_digits
from app.services.fiscal.nfe_xml import NFeParseError, parse_nfe_xml
from app.services.fiscal.photo import PhotoReadError, read_photo
from app.services.fiscal.validation import validate
from app.tenancy import user_session

logger = logging.getLogger(__name__)


def upload_dir() -> Path:
    path = Path(get_settings().upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def upsert_supplier(db: Session, cnpj: str | None, name: str | None) -> Supplier | None:
    cnpj = only_digits(cnpj or "") or None
    if cnpj is None and not name:
        return None
    if cnpj:
        supplier = db.scalar(select(Supplier).where(Supplier.cnpj == cnpj))
    else:  # sem CNPJ (ex.: lançamento manual), reaproveita pelo nome
        supplier = db.scalar(select(Supplier).where(Supplier.cnpj.is_(None), Supplier.name == name))
    if supplier is None:
        supplier = Supplier(cnpj=cnpj, name=(name or "Fornecedor sem nome")[:160])
        db.add(supplier)
        db.flush()
    elif name and supplier.name == "Fornecedor sem nome":
        supplier.name = name[:160]
    return supplier


def revalidate(expense: Expense) -> None:
    """Recalcula os problemas e o status (após a leitura ou após uma edição na revisão)."""
    if expense.status in (ExpenseStatus.duplicate, ExpenseStatus.error):
        return
    items = expense.items
    issues = validate(
        items=[(i.quantity, i.unit_price_cents, i.total_cents) for i in items],
        items_expected_cents=expense.items_expected_cents,
        total_cents=expense.total_cents,
        declared_item_count=expense.declared_item_count,
        issuer_cnpj=expense.supplier.cnpj if expense.supplier else None,
        has_issue_date=expense.issue_date is not None,
        uncategorized=sum(1 for i in items if i.category_id is None),
    )
    if expense.source == ExpenseSource.manual:
        # Lançamento manual não tem CNPJ obrigatório nem contagem de itens de documento.
        issues = [i for i in issues if "CNPJ" not in i]
    expense.issues = issues
    expense.status = ExpenseStatus.needs_review if issues else ExpenseStatus.confirmed


def apply_extraction(
    db: Session, expense: Expense, data: ExtractedDocument, provider: LLMProvider | None
) -> None:
    expense.access_key = data.access_key
    expense.model = data.model
    expense.number = data.number
    expense.series = data.series
    expense.issue_date = data.issue_date
    expense.total_cents = data.total_cents
    expense.items_expected_cents = data.items_expected_cents
    expense.declared_item_count = data.declared_item_count
    expense.payment_method = data.payment_method
    expense.raw_text = data.raw_text
    expense.supplier = upsert_supplier(db, data.issuer_cnpj, data.issuer_name)

    if data.access_key:
        original = db.scalar(
            select(Expense).where(
                Expense.access_key == data.access_key,
                Expense.id != expense.id,
                Expense.status.not_in([ExpenseStatus.duplicate, ExpenseStatus.error]),
            )
        )
        if original is not None:
            expense.status = ExpenseStatus.duplicate
            expense.issues = [f"Esta nota já foi lançada (lançamento #{original.id})."]
            return

    expense.items = [
        ExpenseItem(
            position=position,
            code=item.code,
            description=item.description,
            ncm=item.ncm,
            quantity=item.quantity,
            unit=item.unit,
            unit_price_cents=item.unit_price_cents,
            total_cents=item.total_cents,
        )
        for position, item in enumerate(data.items, start=1)
    ]
    db.flush()
    llm_error = categorize_items(
        db,
        expense.items,
        provider,
        get_settings().llm_batch_size,
        supplier=data.issuer_name,
        from_ocr=expense.source == ExpenseSource.photo,
    )
    revalidate(expense)
    notes = list(data.notes) + (
        [f"Categorização por IA indisponível: {llm_error}"] if llm_error else []
    )
    if notes:
        expense.issues = [*expense.issues, *notes]
        expense.status = ExpenseStatus.needs_review


def process_expense(db: Session, expense: Expense, provider: LLMProvider | None) -> None:
    started = time.perf_counter()
    content = (upload_dir() / expense.stored_filename).read_bytes()
    try:
        if expense.source == ExpenseSource.nfe_xml:
            data = parse_nfe_xml(content)
        else:
            data = read_photo(content, provider, get_settings().photo_llm_fallback)
        apply_extraction(db, expense, data, provider)
    except (NFeParseError, PhotoReadError) as exc:
        expense.status = ExpenseStatus.error
        expense.issues = [str(exc)]
    expense.processing_seconds = round(time.perf_counter() - started, 1)


class ExpenseQueue:
    """Fila serial: um documento por vez (OCR e LLM disputam a mesma CPU)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rerun = False
        self.running = False

    def run(self, provider: LLMProvider | None) -> None:
        if not self._lock.acquire(blocking=False):
            self._rerun = True
            return
        try:
            self.running = True
            while True:
                self._rerun = False
                while (next_up := self._next()) is not None:
                    self._process_one(*next_up, provider)
                if not self._rerun:
                    break
        finally:
            self.running = False
            self._lock.release()

    def _next(self) -> tuple[int, int | None] | None:
        """Próximo arquivo da fila (de qualquer usuário) e o dono dele."""
        with SessionLocal() as db:
            row = db.execute(
                select(Expense.id, Expense.user_id)
                .where(
                    Expense.status == ExpenseStatus.processing, Expense.stored_filename.is_not(None)
                )
                .order_by(Expense.id)
                .limit(1)
            ).first()
            return (row[0], row[1]) if row else None

    def _process_one(
        self, expense_id: int, owner: int | None, provider: LLMProvider | None
    ) -> None:
        # Sessão do dono: fornecedor, duplicatas e memória de categorias são as dele.
        with user_session(owner) as db:
            expense = db.get(Expense, expense_id)
            try:
                process_expense(db, expense, provider)
            except Exception:
                logger.exception("Falha ao processar o lançamento %s", expense_id)
                db.rollback()
                expense = db.get(Expense, expense_id)
                expense.status = ExpenseStatus.error
                expense.issues = ["Erro inesperado ao ler o arquivo."]
            db.commit()

    @staticmethod
    def processing_count(db: Session) -> int:
        """`db` é a sessão do usuário logado: conta só os arquivos dele."""
        return (
            db.scalar(
                select(func.count(Expense.id)).where(Expense.status == ExpenseStatus.processing)
            )
            or 0
        )


expense_queue = ExpenseQueue()
