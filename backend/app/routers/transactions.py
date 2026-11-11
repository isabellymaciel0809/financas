import hashlib
import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_llm_provider
from app.models import CategorizedBy, Category, Transaction
from app.routers.dashboard import month_range
from app.schemas import (
    CategorizationJobStatus,
    CategorizeQueued,
    CategoryOut,
    TextEntryIn,
    TextEntryPreview,
    TransactionCreate,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
)
from app.services.background import categorization_job, queue_llm
from app.services.categorizer.llm import LLMProvider
from app.services.categorizer.pipeline import categorize_transactions, remember
from app.services.quick_entry import NotUnderstood, parse_entry, suggest_category
from app.services.text import merchant_key

router = APIRouter(prefix="/transactions", tags=["transações"])


class TransactionUpdateResult(BaseModel):
    transaction: TransactionOut
    similar_updated: int


@router.get("", response_model=TransactionPage)
def list_transactions(
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM"),
    category_id: int | None = None,
    uncategorized: bool = False,
    needs_review: bool = Query(False, description="Sem categoria ou IA com confiança < 0.6"),
    search: str | None = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(Transaction)
    if month:
        start, end = month_range(month)
        query = query.where(Transaction.date >= start, Transaction.date < end)
    if category_id is not None:
        query = query.where(Transaction.category_id == category_id)
    if uncategorized:
        query = query.where(Transaction.category_id.is_(None))
    if needs_review:
        query = query.where(
            (Transaction.category_id.is_(None))
            | ((Transaction.categorized_by == CategorizedBy.llm) & (Transaction.confidence < 0.6))
        )
    if search:
        query = query.where(Transaction.description.ilike(f"%{search}%"))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limit).offset(offset)
    ).all()
    return TransactionPage(items=items, total=total)


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    provider: LLMProvider | None = Depends(get_llm_provider),
):
    tx = Transaction(
        date=payload.date,
        description=payload.description,
        amount_cents=payload.amount_cents,
        merchant_key=merchant_key(payload.description),
        # Lançamentos manuais nunca colidem com linhas importadas.
        fingerprint=hashlib.sha256(f"manual|{uuid.uuid4()}".encode()).hexdigest(),
    )
    db.add(tx)
    if payload.category_id is not None:
        _ensure_category(db, payload.category_id)
        tx.category_id = payload.category_id
        tx.categorized_by = CategorizedBy.manual
        tx.confidence = 1.0
        db.flush()
    else:
        db.flush()
        outcome = categorize_transactions(db, [tx], provider=None)
        queue_llm(background, provider, outcome.stats.none)
    db.commit()
    db.refresh(tx)
    return tx


@router.post("/parse", response_model=TextEntryPreview)
def parse_text_entry(
    payload: TextEntryIn,
    db: Session = Depends(get_db),
    provider: LLMProvider | None = Depends(get_llm_provider),
):
    """Lançamento por texto ("gastei 45 no mercado ontem"): devolve a prévia, sem salvar.

    Para salvar, o frontend manda a prévia (talvez corrigida) para POST /transactions, que
    categoriza com a mesma cascata da importação.
    """
    try:
        entry = parse_entry(payload.texto, date.today(), provider)
    except NotUnderstood as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    suggestion = suggest_category(db, entry.description, entry.amount_cents)
    return TextEntryPreview(
        date=entry.date,
        description=entry.description,
        amount_cents=entry.amount_cents,
        understood_by=entry.understood_by,
        category=CategoryOut.model_validate(suggestion[0]) if suggestion else None,
        category_source=suggestion[1] if suggestion else None,
        warnings=entry.warnings,
    )


@router.patch("/{transaction_id}", response_model=TransactionUpdateResult)
def update_transaction(
    transaction_id: int, payload: TransactionUpdate, db: Session = Depends(get_db)
):
    """Corrige a categoria. A correção vira memória e é aplicada às transações semelhantes."""
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transação não encontrada.")

    if payload.description is not None:
        tx.description = payload.description

    similar_updated = 0
    if "category_id" in payload.model_fields_set:
        if payload.category_id is None:
            tx.category_id, tx.categorized_by, tx.confidence = None, CategorizedBy.none, None
        else:
            _ensure_category(db, payload.category_id)
            tx.category_id = payload.category_id
            tx.categorized_by = CategorizedBy.manual
            tx.confidence = 1.0
            remember(db, tx.merchant_key, payload.category_id)
            similar = db.scalars(
                select(Transaction).where(
                    Transaction.merchant_key == tx.merchant_key,
                    Transaction.id != tx.id,
                    Transaction.categorized_by != CategorizedBy.manual,
                )
            ).all()
            for other in similar:
                other.category_id = payload.category_id
                other.categorized_by = CategorizedBy.memory
                other.confidence = 1.0
            similar_updated = len(similar)

    db.commit()
    db.refresh(tx)
    return TransactionUpdateResult(
        transaction=TransactionOut.model_validate(tx), similar_updated=similar_updated
    )


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transação não encontrada.")
    db.delete(tx)
    db.commit()


@router.post("/categorize", response_model=CategorizeQueued, status_code=status.HTTP_202_ACCEPTED)
def categorize_pending(
    background: BackgroundTasks,
    provider: LLMProvider | None = Depends(get_llm_provider),
    db: Session = Depends(get_db),
):
    """Envia as transações ainda sem categoria para a LLM, em segundo plano."""
    if provider is None or not provider.is_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Nenhuma LLM disponível.")
    pending = categorization_job.status(db).pending
    return CategorizeQueued(queued=queue_llm(background, provider, pending))


@router.get("/categorize/status", response_model=CategorizationJobStatus)
def categorize_status(db: Session = Depends(get_db)):
    """Acompanha o job de categorização em segundo plano (o frontend consulta enquanto roda)."""
    return categorization_job.status(db)


def _ensure_category(db: Session, category_id: int) -> None:
    if db.get(Category, category_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Categoria inexistente.")
