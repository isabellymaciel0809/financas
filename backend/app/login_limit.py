"""Limite de tentativas de login: freia quem tenta adivinhar senhas.

O scrypt deixa cada tentativa cara, mas não impede alguém de testar milhares de senhas. Aqui,
erros seguidos bloqueiam por um tempo (janela deslizante de 15 minutos):

- por usuário: 5 erros bloqueiam aquele usuário, venham de onde vierem;
- por IP: 30 erros bloqueiam aquele endereço (quem testa muitos usuários diferentes).

O limite por IP é bem mais alto porque, no Docker ou atrás de um proxy, todo mundo pode chegar
com o mesmo IP: um limite baixo ali deixaria um erro de digitação de uma pessoa travar as outras.
Usuários que não existem também contam, então o bloqueio não revela quem existe.

Os erros ficam no banco (tabela `login_failures`). Antes ficavam na memória do processo: com
vários processos do servidor, cada um contava os seus, e um reinício zerava tudo. No banco, o
limite vale para todos e sobrevive a reinícios, sem precisar de outro serviço (como o Redis).

Cada operação usa uma sessão própria e grava na hora: o erro precisa ficar registrado mesmo
quando a requisição termina com 401, sem commit. Dois processos que recebem a última tentativa
ao mesmo tempo podem deixar passar uma a mais; para frear força bruta, isso não muda nada.
"""

import math
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import LoginFailure

USER_LIMIT = 5
IP_LIMIT = 30
WINDOW = timedelta(minutes=15)


class LoginLimiter:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    @staticmethod
    def _user_key(username: str) -> str:
        return f"usuario:{username.strip().casefold()}"[:120]

    def _keys(self, username: str, ip: str) -> list[tuple[str, int]]:
        return [(self._user_key(username), USER_LIMIT), (f"ip:{ip}"[:120], IP_LIMIT)]

    def retry_after(self, username: str, ip: str) -> int:
        """Segundos até poder tentar de novo; 0 se pode tentar agora."""
        now = self.clock()
        wait = 0.0
        with self.session_factory() as db:
            for key, limit in self._keys(username, ip):
                # O erro mais antigo entre os `limit` mais recentes da janela: quando ele sair da
                # janela, sobram menos de `limit` e a pessoa pode tentar de novo.
                recent = db.scalars(
                    select(LoginFailure.failed_at)
                    .where(LoginFailure.key == key, LoginFailure.failed_at > now - WINDOW)
                    .order_by(LoginFailure.failed_at.desc())
                    .limit(limit)
                ).all()
                if len(recent) >= limit:
                    wait = max(wait, (recent[-1] + WINDOW - now).total_seconds())
        return math.ceil(wait)

    def failed(self, username: str, ip: str) -> None:
        now = self.clock()
        with self.session_factory() as db:
            db.add_all(LoginFailure(key=key, failed_at=now) for key, _ in self._keys(username, ip))
            # Erros fora da janela não contam mais: a tabela não cresce sem limite.
            db.execute(delete(LoginFailure).where(LoginFailure.failed_at <= now - WINDOW))
            db.commit()

    def succeeded(self, username: str) -> None:
        """Acertou a senha: zera os erros do usuário (os do IP continuam contando)."""
        with self.session_factory() as db:
            db.execute(delete(LoginFailure).where(LoginFailure.key == self._user_key(username)))
            db.commit()


login_limiter = LoginLimiter()
