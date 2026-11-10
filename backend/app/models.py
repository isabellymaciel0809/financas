import enum
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CategoryKind(enum.StrEnum):
    expense = "expense"
    income = "income"


class CategorizedBy(enum.StrEnum):
    """De onde veio a categoria de uma transação (rastreabilidade da IA)."""

    manual = "manual"  # usuário escolheu
    memory = "memory"  # aprendido de uma correção anterior do usuário
    rule = "rule"  # regra de palavra-chave
    llm = "llm"  # modelo de linguagem
    none = "none"  # ainda sem categoria


class CategoryScope(enum.StrEnum):
    """Onde a categoria vale: no extrato pessoal, nos lançamentos da empresa ou nos dois.

    Separar evita que a LLM do extrato escolha "Receita de vendas" para uma venda no OLX ou
    "Fretes e entregas" para um saque: com as categorias de empresa na lista, o acerto da LLM no
    conjunto de avaliação caiu de 62% para 51%.
    """

    personal = "personal"
    company = "company"
    both = "both"


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    kind: Mapped[CategoryKind] = mapped_column(Enum(CategoryKind), default=CategoryKind.expense)
    color: Mapped[str] = mapped_column(String(9), default="#64748b")
    icon: Mapped[str] = mapped_column(String(8), default="🏷️")
    # Texto (e não Enum do banco) para a migração ser igual no SQLite e no PostgreSQL.
    scope: Mapped[str] = mapped_column(
        String(10), default=CategoryScope.both, server_default=CategoryScope.both
    )

    def applies_to(self, area: CategoryScope) -> bool:
        return self.scope in (area, CategoryScope.both)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    source_format: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(255))
    # Valores em centavos (int) para evitar erros de arredondamento de float.
    # Negativo = saída (despesa), positivo = entrada (receita).
    amount_cents: Mapped[int] = mapped_column(Integer)
    merchant_key: Mapped[str] = mapped_column(String(120), index=True)
    # Hash de (data, valor, descrição) para não importar a mesma linha duas vezes.
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)

    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    categorized_by: Mapped[CategorizedBy] = mapped_column(
        Enum(CategorizedBy), default=CategorizedBy.none
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    category: Mapped[Category | None] = relationship(lazy="joined")


class MerchantMemory(Base):
    """Associação estabelecimento -> categoria aprendida com as correções do usuário."""

    __tablename__ = "merchant_memory"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_key: Mapped[str] = mapped_column(String(120), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    hits: Mapped[int] = mapped_column(Integer, default=1)


# --- Lançamentos de despesa da empresa -------------------------------------------------------
# Um lançamento pode vir de um XML de NF-e, de uma foto de cupom ou ser digitado à mão, e pode
# estar ligado a um funcionário (folha, benefícios ou reembolso de despesa paga por ele).


class ExpenseStatus(enum.StrEnum):
    processing = "processing"  # na fila / sendo lido
    needs_review = "needs_review"  # alguma validação falhou: um humano confere
    confirmed = "confirmed"  # lançamento pronto (automático ou revisado)
    duplicate = "duplicate"  # mesma chave de acesso de um lançamento existente
    error = "error"  # não foi possível ler o arquivo


class ExpenseSource(enum.StrEnum):
    nfe_xml = "nfe_xml"  # XML de NF-e/NFC-e: dados estruturados, leitura exata
    photo = "photo"  # foto do cupom: QR Code + OCR + LLM
    manual = "manual"  # digitado pelo usuário


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    cnpj: Mapped[str | None] = mapped_column(String(14), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(160))


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[ExpenseSource] = mapped_column(Enum(ExpenseSource))
    status: Mapped[ExpenseStatus] = mapped_column(
        Enum(ExpenseStatus), default=ExpenseStatus.processing, index=True
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    total_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(60), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    # Pago do bolso do funcionário: a empresa deve devolver o valor a ele.
    reimbursable: Mapped[bool] = mapped_column(default=False)
    # Nº da proposta/obra do cliente a que o lançamento pertence (custo de um serviço).
    proposal: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    # Classificação da planilha da empresa: Custo, Despesas, Estoque, Receita, Caixa...
    entry_type: Mapped[str] = mapped_column(String(30), default="Despesa", server_default="Despesa")

    # Linha importada da planilha da empresa: impressão digital para não importar duas vezes.
    import_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Arquivo de origem (XML ou foto), guardado em UPLOAD_DIR.
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stored_filename: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Dados fiscais
    access_key: Mapped[str | None] = mapped_column(String(44), index=True, nullable=True)
    model: Mapped[str | None] = mapped_column(String(2), nullable=True)  # 55 NF-e, 65 NFC-e
    number: Mapped[str | None] = mapped_column(String(9), nullable=True)
    series: Mapped[str | None] = mapped_column(String(3), nullable=True)
    declared_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_expected_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Problemas encontrados nas validações e texto bruto do OCR, para a revisão.
    issues: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    supplier: Mapped[Supplier | None] = relationship(lazy="joined")
    employee: Mapped[Employee | None] = relationship(lazy="joined")
    items: Mapped[list["ExpenseItem"]] = relationship(
        back_populates="expense",
        cascade="all, delete-orphan",
        order_by="ExpenseItem.position",
        lazy="selectin",
    )

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def has_file(self) -> bool:
        return self.stored_filename is not None

    @property
    def from_spreadsheet(self) -> bool:
        return self.import_key is not None


class ExpenseItem(Base):
    __tablename__ = "expense_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    description: Mapped[str] = mapped_column(String(255))
    ncm: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    unit_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cents: Mapped[int] = mapped_column(Integer)

    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    categorized_by: Mapped[CategorizedBy] = mapped_column(
        Enum(CategorizedBy), default=CategorizedBy.none
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    expense: Mapped[Expense] = relationship(back_populates="items")
    category: Mapped[Category | None] = relationship(lazy="joined")
