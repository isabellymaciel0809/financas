"""Limite de tentativas de login: freia quem tenta adivinhar senhas.

O scrypt deixa cada tentativa cara, mas não impede alguém de testar milhares de senhas. Aqui,
erros seguidos bloqueiam por um tempo (janela deslizante de 15 minutos):

- por usuário: 5 erros bloqueiam aquele usuário, venham de onde vierem;
- por IP: 30 erros bloqueiam aquele endereço (quem testa muitos usuários diferentes).

O limite por IP é bem mais alto porque, no Docker ou atrás de um proxy, todo mundo pode chegar
com o mesmo IP: um limite baixo ali deixaria um erro de digitação de uma pessoa travar as outras.
Usuários que não existem também contam, então o bloqueio não revela quem existe.

Limitação consciente: o estado fica em memória, como as filas (app/services/background.py). Vale
para um único processo do servidor; com vários, o caminho seria guardar as tentativas no Redis.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable

USER_LIMIT = 5
IP_LIMIT = 30
WINDOW_SECONDS = 15 * 60
MAX_KEYS = 10_000  # acima disso, limpa as chaves vencidas (memória não cresce sem limite)


class LoginLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _keys(username: str, ip: str) -> list[tuple[str, int]]:
        return [(f"usuario:{username.strip().casefold()}", USER_LIMIT), (f"ip:{ip}", IP_LIMIT)]

    def _recent(self, key: str, now: float) -> deque[float]:
        failures = self._failures.get(key, deque())
        while failures and failures[0] <= now - WINDOW_SECONDS:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)
        return failures

    def retry_after(self, username: str, ip: str) -> int:
        """Segundos até poder tentar de novo; 0 se pode tentar agora."""
        now = self.clock()
        wait = 0.0
        with self._lock:
            for key, limit in self._keys(username, ip):
                failures = self._recent(key, now)
                if len(failures) >= limit:
                    wait = max(wait, failures[-limit] + WINDOW_SECONDS - now)
        return math.ceil(wait)

    def failed(self, username: str, ip: str) -> None:
        now = self.clock()
        with self._lock:
            if len(self._failures) > MAX_KEYS:
                for key in list(self._failures):
                    self._recent(key, now)
            for key, _ in self._keys(username, ip):
                self._failures.setdefault(key, deque()).append(now)

    def succeeded(self, username: str) -> None:
        """Acertou a senha: zera os erros do usuário (os do IP continuam contando)."""
        with self._lock:
            self._failures.pop(self._keys(username, "")[0][0], None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = LoginLimiter()
