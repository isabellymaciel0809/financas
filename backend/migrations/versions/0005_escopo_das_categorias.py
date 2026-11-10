"""escopo das categorias

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Cópia fixa (migrações não importam o código do app, que muda com o tempo).
COMPANY = (
    "Materiais e manutenção",
    "Ferramentas e equipamentos",
    "Limpeza e higiene",
    "Escritório e informática",
    "Serviços de terceiros",
    "Fretes e entregas",
    "Salários e pró-labore",
    "Encargos trabalhistas",
    "Benefícios a funcionários",
    "Receita de serviços",
    "Receita de vendas",
)
PERSONAL = ("Salário", "Renda extra", "Rendimentos")


def upgrade() -> None:
    """Onde cada categoria vale: extrato pessoal, lançamentos da empresa ou os dois.

    Categorias criadas pelo usuário ficam em "both", como antes desta migração."""
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("scope", sa.String(length=10), server_default="both", nullable=False)
        )
    categories = sa.table("categories", sa.column("name", sa.String), sa.column("scope", sa.String))
    for scope, names in (("company", COMPANY), ("personal", PERSONAL)):
        op.execute(categories.update().where(categories.c.name.in_(names)).values(scope=scope))


def downgrade() -> None:
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.drop_column("scope")
