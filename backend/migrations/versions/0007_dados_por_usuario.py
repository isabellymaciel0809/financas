"""dados por usuario

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNED = (
    "import_batches",
    "transactions",
    "merchant_memory",
    "suppliers",
    "employees",
    "expenses",
    "expense_items",
)
# Unicidades que passam a valer por usuário: tabela -> (coluna antiga, nome da nova).
PER_USER_UNIQUE = {
    "categories": ("name", "uq_categories_user_name"),
    "transactions": ("fingerprint", "uq_transactions_user_fingerprint"),
    "merchant_memory": ("merchant_key", "uq_merchant_memory_user_key"),
    "suppliers": ("cnpj", "uq_suppliers_user_cnpj"),
}
# As unicidades de 0001 não têm nome. No SQLite, a convenção abaixo dá um nome a elas ao recriar
# a tabela; no PostgreSQL, o nome é o que o próprio banco gerou (tabela_coluna_key).
CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def _old_unique_name(table: str, column: str) -> str:
    if op.get_bind().dialect.name == "sqlite":
        return f"uq_{table}_{column}"
    return f"{table}_{column}_key"


def upgrade() -> None:
    """Cada usuário passa a ter os próprios dados (filtro central em app/tenancy.py).

    Linhas que já existem vão para o primeiro usuário cadastrado; se ainda não houver nenhum,
    ficam sem dono e são transferidas para a primeira conta criada (POST /api/auth/setup).
    Categorias existentes continuam sem dono: são as padrão, que valem para todos."""
    for table in ("categories", *OWNED):
        with op.batch_alter_table(table, naming_convention=CONVENTION) as batch_op:
            batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch_op.create_index(f"ix_{table}_user_id", ["user_id"], unique=False)
            batch_op.create_foreign_key(
                f"fk_{table}_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
            )
            if table in PER_USER_UNIQUE:
                column, new_name = PER_USER_UNIQUE[table]
                batch_op.drop_constraint(_old_unique_name(table, column), type_="unique")
                batch_op.create_unique_constraint(new_name, ["user_id", column])

    for table in OWNED:
        op.execute(
            f"UPDATE {table} SET user_id = (SELECT MIN(id) FROM users) WHERE user_id IS NULL"
        )


def downgrade() -> None:
    for table in reversed(("categories", *OWNED)):
        with op.batch_alter_table(table, naming_convention=CONVENTION) as batch_op:
            if table in PER_USER_UNIQUE:
                column, new_name = PER_USER_UNIQUE[table]
                batch_op.drop_constraint(new_name, type_="unique")
                batch_op.create_unique_constraint(_old_unique_name(table, column), [column])
            batch_op.drop_constraint(f"fk_{table}_user_id_users", type_="foreignkey")
            batch_op.drop_index(f"ix_{table}_user_id")
            batch_op.drop_column("user_id")
