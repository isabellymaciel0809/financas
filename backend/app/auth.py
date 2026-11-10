"""Login: senhas com scrypt, sessões por cookie e HTTP Basic para o Power BI.

- Navegador: POST /api/auth/login devolve um cookie HttpOnly com um token aleatório. O banco
  guarda só o SHA-256 do token, então um vazamento do banco não abre sessões.
- Power BI / scripts: não guardam cookie, então as rotas aceitam também HTTP Basic (usuário
  e senha), que o Power BI oferece em "Obter dados > Web > Básico".
- Primeiro acesso: sem nenhum usuário cadastrado, a tela pede para criar a conta (setup).
"""

import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User, UserSession
from app.tenancy import bind_user

COOKIE_NAME = "financas_sessao"
SESSION_DAYS = 30
# Parâmetros do scrypt (RFC 7914): ~16 MB de memória por tentativa, o que encarece força bruta.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = stored.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), expected)


# Para quem erra o usuário levar o mesmo tempo de quem erra a senha (não revela quem existe).
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username.strip().casefold()))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    return user if verify_password(password, user.password_hash) else None


def create_user(db: Session, username: str, password: str) -> User:
    name = username.strip().casefold()
    if not name:
        raise ValueError("Informe o usuário.")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres.")
    if db.scalar(select(User).where(User.username == name)):
        raise ValueError("Já existe um usuário com esse nome.")
    user = User(username=name, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user


def set_password(db: Session, user: User, password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres.")
    user.password_hash = hash_password(password)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))  # derruba sessões


def has_users(db: Session) -> bool:
    return bool(db.scalar(select(func.count(User.id))))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def open_session(db: Session, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    db.execute(delete(UserSession).where(UserSession.expires_at < now))  # limpa as vencidas
    db.add(
        UserSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=now + timedelta(days=SESSION_DAYS),
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,  # JavaScript não lê o cookie (protege contra XSS roubar a sessão)
        samesite="lax",  # outro site não consegue enviar POST com o cookie (CSRF)
        secure=get_settings().cookie_secure,  # ligue em produção, com HTTPS
    )


def close_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE_NAME)


def _from_cookie(db: Session, request: Request) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    if session is None or session.expires_at < datetime.now():
        return None
    return session.user


def _from_basic_auth(db: Session, request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        username, _, password = base64.b64decode(encoded).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    return authenticate(db, username, password)


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependência das rotas protegidas: sessão do navegador ou HTTP Basic."""
    user = _from_cookie(db, request) or _from_basic_auth(db, request)
    if user is None:
        # Pede Basic só ao Power BI (rotas /bi) e a quem já tentou Basic. Nas demais rotas, o
        # cabeçalho faria o navegador abrir a janela de senha dele por cima da tela de login.
        challenge = request.url.path.startswith("/api/bi/") or request.headers.get("authorization")
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Entre com seu usuário e senha.",
            headers={"WWW-Authenticate": 'Basic realm="Financas IA", charset="UTF-8"'}
            if challenge
            else None,
        )
    bind_user(db, user.id)  # daqui em diante, esta sessão só enxerga os dados deste usuário
    return user
