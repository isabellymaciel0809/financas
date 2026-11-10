from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (
    authenticate,
    close_session,
    create_user,
    has_users,
    open_session,
    require_user,
    set_password,
    verify_password,
)
from app.database import get_db
from app.models import User
from app.tenancy import claim_unowned_data

router = APIRouter(prefix="/auth", tags=["login"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class AuthStatus(BaseModel):
    setup_required: bool  # nenhum usuário ainda: a tela mostra "criar conta"
    username: str | None = None


@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request, db: Session = Depends(get_db)):
    """Público: diz se é o primeiro acesso e, se houver sessão, quem está logado."""
    if not has_users(db):
        return AuthStatus(setup_required=True)
    try:
        user = require_user(request, db)
    except HTTPException:
        return AuthStatus(setup_required=False)
    return AuthStatus(setup_required=False, username=user.username)


@router.post("/setup", response_model=AuthStatus, status_code=status.HTTP_201_CREATED)
def setup(payload: Credentials, response: Response, db: Session = Depends(get_db)):
    """Cria o primeiro usuário. Depois disso, novos usuários só por quem já entrou."""
    if has_users(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "O sistema já tem usuário. Faça login.")
    try:
        user = create_user(db, payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    # O que foi usado/importado antes de existir login passa a ser desta primeira conta.
    claim_unowned_data(db, user.id)
    open_session(db, user, response)
    return AuthStatus(setup_required=False, username=user.username)


@router.post("/login", response_model=AuthStatus)
def login(payload: Credentials, response: Response, db: Session = Depends(get_db)):
    user = authenticate(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário ou senha incorretos.")
    open_session(db, user, response)
    return AuthStatus(setup_required=False, username=user.username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    close_session(db, request, response)


@router.post("/users", response_model=AuthStatus, status_code=status.HTTP_201_CREATED)
def add_user(payload: Credentials, db: Session = Depends(get_db), _: User = Depends(require_user)):
    """Cadastra outra pessoa. Ela começa com o organizador vazio: os dados são de cada um."""
    try:
        user = create_user(db, payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    return AuthStatus(setup_required=False, username=user.username)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Senha atual incorreta.")
    try:
        set_password(db, user, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    open_session(db, user, response)  # as outras sessões caem; esta continua
