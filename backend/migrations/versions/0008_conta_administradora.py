"""conta administradora

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-11 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Só quem administra cadastra outras pessoas. Num banco existente, é a primeira conta."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    op.execute("UPDATE users SET is_admin = TRUE WHERE id = (SELECT MIN(id) FROM users)")


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("is_admin")
