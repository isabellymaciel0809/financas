"""tentativas de login no banco

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Os erros de login saem da memória do processo: valem para todos os processos."""
    op.create_table(
        "login_failures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("failed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_failures_key_failed_at", "login_failures", ["key", "failed_at"], unique=False
    )
    op.create_index(
        op.f("ix_login_failures_failed_at"), "login_failures", ["failed_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_login_failures_failed_at"), table_name="login_failures")
    op.drop_index("ix_login_failures_key_failed_at", table_name="login_failures")
    op.drop_table("login_failures")
