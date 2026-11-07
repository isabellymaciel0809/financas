import uuid
from datetime import date
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_llm_provider
from app.models import (
    CategorizedBy,
    Category,
    Employee,
    Expense,
    ExpenseItem,
    ExpenseSource,
    ExpenseStatus,
)
from app.routers.dashboard import month_range
from app.schemas import (
    ExpenseDetail,
    ExpenseItemIn,
    ExpenseQueueStatus,
    ExpenseSummary,
    ExpenseUpdate,
    ItemsReport,
    ManualExpenseCreate,
)
from app.services.categorizer.llm import LLMProvider
from app.services.categorizer.pipeline import remember
from app.services.fiscal.entry_types import INCOME_TYPES, default_entry_type
from app.services.fiscal.export import build_items_workbook, build_workbook
from app.services.fiscal.items import categorize_items
from app.services.fiscal.items_report import ItemFilters, build_report, query_items, to_row
from app.services.fiscal.processor import expense_queue, revalidate, upload_dir, upsert_supplier
from app.services.text import merchant_key

router = APIRouter(prefix="/expenses", tags=["lançamentos"])

PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
XML_TYPES = {".xml"}


@router.post("/upload", response_model=list[ExpenseSummary], status_code=status.HTTP_202_ACCEPTED)
async def upload(
    background: BackgroundTasks,
    files: list[UploadFile] = File(..., description="XML de NF-e/NFC-e ou fotos de cupons"),
    proposal: str | None = Form(None, max_length=40, description="Proposta/obra do lote"),
    entry_type: str | None = Form(None, max_length=30, description="Tipo (Custo, Estoque...)"),
    db: Session = Depends(get_db),
    provider: LLMProvider | None = Depends(get_llm_provider),
):
    """Recebe os arquivos e responde na hora; a leitura acontece numa fila em segundo plano."""
    proposal = (proposal or "").strip() or None
    entry_type = (entry_type or "").strip() or default_entry_type(proposal)
    limit = get_settings().max_upload_mb * 1024 * 1024
    created = []
    for file in files:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in PHOTO_TYPES | XML_TYPES:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"{file.filename}: envie XML de nota ou foto (JPG, PNG, WEBP).",
            )
        content = await file.read(limit + 1)
        if len(content) > limit:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"{file.filename}: maior que {get_settings().max_upload_mb} MB.",
            )
        # Nome aleatório no disco: o nome enviado nunca vira caminho (evita path traversal).
        stored = f"{uuid.uuid4().hex}{suffix}"
        (upload_dir() / stored).write_bytes(content)
        expense = Expense(
            source=ExpenseSource.nfe_xml if suffix in XML_TYPES else ExpenseSource.photo,
            status=ExpenseStatus.processing,
            original_filename=(file.filename or stored)[:255],
            stored_filename=stored,
            proposal=proposal,
            entry_type=entry_type,
            issues=[],
        )
        db.add(expense)
        created.append(expense)
    db.commit()
    background.add_task(expense_queue.run, provider)
    return created


@router.post("", response_model=ExpenseDetail, status_code=status.HTTP_201_CREATED)
def create_manual(
    payload: ManualExpenseCreate,
    db: Session = Depends(get_db),
    provider: LLMProvider | None = Depends(get_llm_provider),
):
    """Lançamento digitado: despesa sem nota, folha de pagamento, benefício etc."""
    _ensure_employee(db, payload.employee_id)
    proposal = (payload.proposal or "").strip() or None
    expense = Expense(
        source=ExpenseSource.manual,
        proposal=proposal,
        entry_type=(payload.entry_type or "").strip() or default_entry_type(proposal),
        description=payload.description,
        issue_date=payload.issue_date,
        payment_method=payload.payment_method,
        employee_id=payload.employee_id,
        reimbursable=payload.reimbursable,
        supplier=upsert_supplier(db, payload.supplier_cnpj, payload.supplier_name),
        issues=[],
    )
    db.add(expense)
    _replace_items(db, expense, payload.items)
    expense.total_cents = sum(i.total_cents for i in expense.items)
    db.flush()
    # Sem categoria escolhida: só regras e memória (instantâneo); a LLM fica para a revisão.
    # Receitas não passam pelas regras, que são de despesa.
    if expense.entry_type not in INCOME_TYPES:
        categorize_items(db, expense.items, provider=None)
    revalidate(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("", response_model=list[ExpenseSummary])
def list_expenses(
    status_filter: ExpenseStatus | None = Query(None, alias="status"),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    employee_id: int | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return db.scalars(_filtered(status_filter, month, employee_id).limit(limit)).unique().all()


@router.get("/proposals", response_model=list[str])
def list_proposals(db: Session = Depends(get_db)):
    """Propostas já usadas, para o autocompletar da interface."""
    rows = db.scalars(
        select(Expense.proposal).where(Expense.proposal.is_not(None)).distinct()
    ).all()
    return sorted(rows)


@router.get("/queue", response_model=ExpenseQueueStatus)
def queue_status():
    return ExpenseQueueStatus(
        running=expense_queue.running, processing=expense_queue.processing_count()
    )


@router.get("/export.xlsx")
def export(
    status_filter: ExpenseStatus | None = Query(ExpenseStatus.confirmed, alias="status"),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
):
    expenses = db.scalars(_filtered(status_filter, month, None)).unique().all()
    name = f"lancamentos-{month or date.today().isoformat()}.xlsx"
    return Response(
        build_workbook(expenses),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _item_filters(
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    proposal: str | None = Query(None, max_length=40),
    entry_type: str | None = Query(None, max_length=30),
    category_id: int | None = None,
    search: str | None = Query(None, max_length=100),
    only_confirmed: bool = False,
) -> ItemFilters:
    return ItemFilters(
        month, proposal or None, entry_type or None, category_id, search, only_confirmed
    )


@router.get("/items", response_model=ItemsReport)
def list_items(filters: ItemFilters = Depends(_item_filters), db: Session = Depends(get_db)):
    """Todos os itens de todas as notas, filtrados, com totais por tipo e por categoria."""
    return build_report(db, filters)


@router.get("/items/export.xlsx")
def export_items(filters: ItemFilters = Depends(_item_filters), db: Session = Depends(get_db)):
    """Exporta exatamente o que está filtrado na tela de itens, no formato da planilha."""
    rows = [to_row(item, expense) for item, expense in query_items(db, filters)]
    name = f"itens-{filters.month or date.today().isoformat()}.xlsx"
    return Response(
        build_items_workbook(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/{expense_id}", response_model=ExpenseDetail)
def get_expense(expense_id: int, db: Session = Depends(get_db)):
    return _get(db, expense_id)


@router.get("/{expense_id}/file")
def get_file(expense_id: int, db: Session = Depends(get_db)):
    expense = _get(db, expense_id)
    if not expense.stored_filename:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lançamento sem arquivo.")
    return FileResponse(upload_dir() / expense.stored_filename, filename=expense.original_filename)


@router.patch("/{expense_id}", response_model=ExpenseDetail)
def update_expense(expense_id: int, payload: ExpenseUpdate, db: Session = Depends(get_db)):
    """Correções da revisão. Cada categoria corrigida vira memória para as próximas notas."""
    expense = _get(db, expense_id)
    if expense.status == ExpenseStatus.processing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aguarde a leitura terminar.")
    fields = payload.model_fields_set
    for name in ("description", "issue_date", "total_cents", "payment_method", "reimbursable"):
        if name in fields:
            setattr(expense, name, getattr(payload, name))
    if "proposal" in fields:
        expense.proposal = (payload.proposal or "").strip() or None
    if "entry_type" in fields and payload.entry_type:
        expense.entry_type = payload.entry_type.strip()
    if "employee_id" in fields:
        _ensure_employee(db, payload.employee_id)
        expense.employee_id = payload.employee_id
    if fields & {"supplier_name", "supplier_cnpj"}:
        current = expense.supplier
        expense.supplier = upsert_supplier(
            db,
            payload.supplier_cnpj if "supplier_cnpj" in fields else current and current.cnpj,
            payload.supplier_name if "supplier_name" in fields else current and current.name,
        )
        if expense.supplier and "supplier_name" in fields and payload.supplier_name:
            expense.supplier.name = payload.supplier_name
    if payload.items is not None:
        _replace_items(db, expense, payload.items)
        if expense.source == ExpenseSource.manual:
            expense.total_cents = sum(i.total_cents for i in expense.items)
    db.flush()
    if expense.status != ExpenseStatus.duplicate:
        expense.status = ExpenseStatus.needs_review  # revalidate decide o status final
        revalidate(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.post("/{expense_id}/confirm", response_model=ExpenseDetail)
def confirm(expense_id: int, db: Session = Depends(get_db)):
    """Confirma após revisão humana, mesmo com avisos (que ficam registrados)."""
    expense = _get(db, expense_id)
    if expense.status in (ExpenseStatus.processing, ExpenseStatus.duplicate, ExpenseStatus.error):
        raise HTTPException(status.HTTP_409_CONFLICT, "Este lançamento não pode ser confirmado.")
    expense.status = ExpenseStatus.confirmed
    db.commit()
    db.refresh(expense)
    return expense


@router.post("/{expense_id}/reprocess", response_model=ExpenseDetail)
def reprocess(
    expense_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    provider: LLMProvider | None = Depends(get_llm_provider),
):
    expense = _get(db, expense_id)
    if not expense.stored_filename:
        raise HTTPException(status.HTTP_409_CONFLICT, "Lançamento manual não tem arquivo para ler.")
    expense.status = ExpenseStatus.processing
    expense.issues = []
    expense.items = []
    db.commit()
    background.add_task(expense_queue.run, provider)
    db.refresh(expense)
    return expense


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = _get(db, expense_id)
    if expense.stored_filename:
        (upload_dir() / expense.stored_filename).unlink(missing_ok=True)
    db.delete(expense)
    db.commit()


# --- auxiliares ------------------------------------------------------------------------------


def _filtered(status_filter: ExpenseStatus | None, month: str | None, employee_id: int | None):
    query = select(Expense).order_by(Expense.id.desc())
    if status_filter is not None:
        query = query.where(Expense.status == status_filter)
    if month:
        start, end = month_range(month)
        query = query.where(Expense.issue_date >= start, Expense.issue_date < end)
    if employee_id is not None:
        query = query.where(Expense.employee_id == employee_id)
    return query


def _get(db: Session, expense_id: int) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lançamento não encontrado.")
    return expense


def _ensure_employee(db: Session, employee_id: int | None) -> None:
    if employee_id is not None and db.get(Employee, employee_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Funcionário inexistente.")


def _replace_items(db: Session, expense: Expense, items: list[ExpenseItemIn]) -> None:
    previous = {i.id: i for i in expense.items}
    new_items = []
    for position, data in enumerate(items, start=1):
        if data.category_id is not None and db.get(Category, data.category_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Categoria inexistente.")
        old = previous.get(data.id) if data.id is not None else None
        item = ExpenseItem(
            position=position,
            code=data.code,
            description=data.description,
            quantity=data.quantity,
            unit=data.unit,
            unit_price_cents=data.unit_price_cents,
            total_cents=data.total_cents,
            category_id=data.category_id,
        )
        if data.category_id is None:
            item.categorized_by = CategorizedBy.none
        elif old is not None and old.category_id == data.category_id:
            item.categorized_by, item.confidence = old.categorized_by, old.confidence
        else:
            # Categoria escolhida pelo usuário: vale como correção e é memorizada.
            item.categorized_by, item.confidence = CategorizedBy.manual, 1.0
            remember(db, merchant_key(data.description), data.category_id)
        new_items.append(item)
    expense.items = new_items
