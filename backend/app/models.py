import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Integer, String, func
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


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    kind: Mapped[CategoryKind] = mapped_column(Enum(CategoryKind), default=CategoryKind.expense)
    color: Mapped[str] = mapped_column(String(9), default="#64748b")
    icon: Mapped[str] = mapped_column(String(8), default="🏷️")


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
