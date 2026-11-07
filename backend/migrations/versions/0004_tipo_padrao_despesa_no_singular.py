"""tipo padrao despesa no singular

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-07 20:10:41.102961

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Tipo padrão "Despesa" (singular), como na planilha da empresa: as fórmulas do DRE somam
    por esse texto exato. Lançamentos já gravados como "Despesas" passam a "Despesa"."""
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.alter_column(
            "entry_type",
            existing_type=sa.String(length=30),
            server_default="Despesa",
            existing_nullable=False,
        )
    op.execute("UPDATE expenses SET entry_type = 'Despesa' WHERE entry_type = 'Despesas'")


def downgrade() -> None:
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.alter_column(
            "entry_type",
            existing_type=sa.String(length=30),
            server_default="Despesas",
            existing_nullable=False,
        )
