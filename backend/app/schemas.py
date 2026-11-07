from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models import CategorizedBy, CategoryKind, ExpenseSource, ExpenseStatus


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: CategoryKind
    color: str
    icon: str


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: CategoryKind = CategoryKind.expense
    color: str = Field(default="#64748b", pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str = Field(default="🏷️", max_length=8)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    description: str
    amount_cents: int
    category: CategoryOut | None
    categorized_by: CategorizedBy
    confidence: float | None


class TransactionCreate(BaseModel):
    date: date
    description: str = Field(min_length=1, max_length=255)
    amount_cents: int = Field(description="Negativo para despesa, positivo para receita")
    category_id: int | None = None


class TransactionUpdate(BaseModel):
    category_id: int | None = None
    description: str | None = Field(default=None, min_length=1, max_length=255)


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int


class CategorizationStats(BaseModel):
    memory: int = 0
    rule: int = 0
    llm: int = 0
    none: int = 0


class ImportResult(BaseModel):
    filename: str
    source_format: str
    imported: int
    duplicates: int
    categorization: CategorizationStats
    # Transações enviadas para a LLM em segundo plano (acompanhe em /categorize/status).
    llm_queued: int = 0
    llm_error: str | None = None


class CategorizeQueued(BaseModel):
    queued: int


class CategorizationJobStatus(BaseModel):
    running: bool
    pending: int
    last_categorized: int
    last_error: str | None


class CategoryTotal(BaseModel):
    category_id: int | None
    name: str
    color: str
    icon: str
    total_cents: int


class MonthTotal(BaseModel):
    month: str  # YYYY-MM
    income_cents: int
    expense_cents: int


class DashboardSummary(BaseModel):
    month: str
    income_cents: int
    expense_cents: int
    balance_cents: int
    transaction_count: int
    expenses_by_category: list[CategoryTotal]
    monthly: list[MonthTotal]
    categorized_by: CategorizationStats


class HealthOut(BaseModel):
    status: str
    llm_provider: str
    llm_model: str | None
    llm_available: bool


# --- Lançamentos de despesa e funcionários --------------------------------------------------


class EmployeeIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str | None = Field(None, max_length=80)
    active: bool = True


class EmployeeOut(EmployeeIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ExpenseItemIn(BaseModel):
    id: int | None = None  # item existente (para manter a origem da categoria)
    description: str = Field(min_length=1, max_length=255)
    total_cents: int = Field(ge=0)
    quantity: float = Field(1.0, gt=0)
    unit: str | None = Field(None, max_length=10)
    unit_price_cents: int | None = Field(None, ge=0)
    code: str | None = Field(None, max_length=60)
    category_id: int | None = None


class ExpenseItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    code: str | None
    description: str
    ncm: str | None
    quantity: float
    unit: str | None
    unit_price_cents: int | None
    total_cents: int
    category: CategoryOut | None
    categorized_by: CategorizedBy
    confidence: float | None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cnpj: str | None
    name: str


class ExpenseSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: ExpenseSource
    status: ExpenseStatus
    issue_date: date | None
    description: str | None
    supplier: SupplierOut | None
    employee: EmployeeOut | None
    reimbursable: bool
    proposal: str | None
    entry_type: str
    from_spreadsheet: bool
    number: str | None
    total_cents: int | None
    original_filename: str | None
    issues: list[str]
    item_count: int
    processing_seconds: float | None


class ExpenseDetail(ExpenseSummary):
    access_key: str | None
    model: str | None
    series: str | None
    payment_method: str | None
    declared_item_count: int | None
    items_expected_cents: int | None
    raw_text: str | None
    has_file: bool
    items: list[ExpenseItemOut]


class ExpenseUpdate(BaseModel):
    description: str | None = Field(None, max_length=255)
    issue_date: date | None = None
    total_cents: int | None = Field(None, ge=0)
    payment_method: str | None = Field(None, max_length=60)
    supplier_name: str | None = Field(None, max_length=160)
    supplier_cnpj: str | None = Field(None, max_length=18)
    employee_id: int | None = None
    reimbursable: bool | None = None
    proposal: str | None = Field(None, max_length=40)
    entry_type: str | None = Field(None, min_length=1, max_length=30)
    items: list[ExpenseItemIn] | None = None


class ManualExpenseCreate(BaseModel):
    issue_date: date
    description: str = Field(min_length=1, max_length=255)
    items: list[ExpenseItemIn] = Field(min_length=1, max_length=200)
    supplier_name: str | None = Field(None, max_length=160)
    supplier_cnpj: str | None = Field(None, max_length=18)
    payment_method: str | None = Field(None, max_length=60)
    employee_id: int | None = None
    reimbursable: bool = False
    proposal: str | None = Field(None, max_length=40)
    entry_type: str | None = Field(None, min_length=1, max_length=30)


class ExpenseQueueStatus(BaseModel):
    running: bool
    processing: int


class ItemRow(BaseModel):
    """Um item de lançamento com os dados da nota, no formato da planilha."""

    id: int
    expense_id: int
    expense_status: ExpenseStatus
    issue_date: date | None
    counterpart: str | None
    proposal: str | None
    description: str
    entry_type: str
    category: CategoryOut | None
    quantity: float
    unit: str | None
    unit_price_cents: int | None
    total_cents: int


class GroupTotal(BaseModel):
    name: str
    total_cents: int
    count: int


class ItemsReport(BaseModel):
    items: list[ItemRow]
    count: int
    total_cents: int
    by_type: list[GroupTotal]
    by_category: list[GroupTotal]
    truncated: bool


class SpreadsheetImportResult(BaseModel):
    sheet: str
    imported: int
    duplicates: int
    already_in_system: int
    needs_review: int
    skipped: int
    skipped_rows: list[int]
    skip_reasons: dict[str, int]
