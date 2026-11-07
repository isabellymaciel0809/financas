from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models import CategorizedBy, CategoryKind


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
    llm_error: str | None = None


class CategorizeResult(BaseModel):
    processed: int
    categorization: CategorizationStats
    llm_error: str | None = None


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
