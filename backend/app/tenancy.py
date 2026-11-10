"""Cada usuário tem os próprios dados: um não vê nada do outro.

Em vez de lembrar de filtrar cada consulta (e esquecer uma), o filtro é central:

- Uma sessão "de usuário" (`bind_user`) só enxerga linhas desse usuário. Um evento do SQLAlchemy
  acrescenta `user_id = X` a toda consulta, atualização e exclusão das tabelas com dono, inclusive
  nas relações carregadas depois (itens de um lançamento, categoria de uma transação...).
- Toda linha nova numa sessão de usuário recebe o dono automaticamente.
- Categorias são a exceção: as padrão (`user_id` vazio) valem para todos, e cada usuário vê
  também as que ele mesmo criou.

Uma sessão sem usuário (inicialização, migrações, testes de unidade, avaliação da IA) não tem
filtro. Por isso o app só entrega dados por rotas que exigem login (`require_user` chama
`bind_user`), e as filas em segundo plano abrem uma sessão por dono.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event, or_, update
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.database import SessionLocal
from app.models import (
    Category,
    Employee,
    Expense,
    ExpenseItem,
    ImportBatch,
    MerchantMemory,
    Supplier,
    Transaction,
)

OWNED = (Transaction, ImportBatch, MerchantMemory, Expense, ExpenseItem, Employee, Supplier)
SHARED_DEFAULTS = (Category,)  # vazio = padrão para todos
USER_KEY = "user_id"
ALL_USERS = "all_users"


def bind_user(db: Session, user_id: int) -> None:
    db.info[USER_KEY] = user_id


def current_user_id(db: Session) -> int | None:
    return db.info.get(USER_KEY)


@contextmanager
def user_session(user_id: int | None) -> Iterator[Session]:
    """Sessão para trabalho em segundo plano em nome de um usuário (ou sem dono, se None)."""
    with SessionLocal() as db:
        if user_id is not None:
            bind_user(db, user_id)
        yield db


@event.listens_for(Session, "do_orm_execute")
def _only_own_rows(state: ORMExecuteState) -> None:
    user_id = state.session.info.get(USER_KEY)
    if user_id is None or not (state.is_select or state.is_update or state.is_delete):
        return
    if state.execution_options.get(ALL_USERS):  # uso interno explícito (ex.: claim_unowned_data)
        return
    options = [
        with_loader_criteria(model, lambda cls: cls.user_id == user_id, include_aliases=True)
        for model in OWNED
    ]
    options += [
        with_loader_criteria(
            model,
            lambda cls: or_(cls.user_id == user_id, cls.user_id.is_(None)),
            include_aliases=True,
        )
        for model in SHARED_DEFAULTS
    ]
    state.statement = state.statement.options(*options)


@event.listens_for(Session, "before_flush")
def _stamp_owner(session: Session, *_) -> None:
    user_id = session.info.get(USER_KEY)
    if user_id is None:
        return
    for obj in session.new:
        if isinstance(obj, OWNED + SHARED_DEFAULTS) and obj.user_id is None:
            obj.user_id = user_id


def claim_unowned_data(db: Session, user_id: int) -> None:
    """Dados criados antes de existir login (ou antes do primeiro usuário) passam a ser dele."""
    for model in OWNED:
        db.execute(
            update(model)
            .where(model.user_id.is_(None))
            .values(user_id=user_id)
            .execution_options(synchronize_session=False, **{ALL_USERS: True})
        )
