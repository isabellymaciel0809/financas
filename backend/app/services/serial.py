"""Trabalho em segundo plano que roda um de cada vez, sem perder pedidos.

As filas (notas e categorização pela LLM) não podem rodar em paralelo: OCR e LLM disputam a
mesma CPU. Quem pede enquanto uma execução está em andamento só deixa um aviso, e ela faz mais
uma rodada no fim, pegando o que chegou.

A versão anterior usava `Lock.acquire(blocking=False)` e uma flag solta, e perdia o aviso numa
janela pequena: a execução conferia a flag, via "nada novo" e, antes de soltar o lock, chegava
um pedido. Esse pedido achava o lock ocupado, deixava o aviso e ia embora; a execução terminava
sem vê-lo, e o trabalho ficava parado até o próximo envio. Aqui, "tem pedido?" e "parei de rodar"
acontecem juntos, sob o mesmo lock, então essa janela não existe.
"""

import threading
from collections.abc import Callable


class SerialRunner:
    def __init__(self) -> None:
        self._state = threading.Lock()
        self._requested = False
        self.running = False

    def trigger(self, round_: Callable[[], bool | None]) -> bool:
        """Pede uma rodada de `round_`.

        Se nada estiver rodando, roda agora, nesta thread, e repete enquanto chegarem pedidos.
        Se já estiver rodando, só deixa o pedido e devolve False na hora. `round_` devolve False
        para parar sem esperar outros pedidos (ex.: LLM fora do ar); eles ficam para o próximo.
        """
        with self._state:
            self._requested = True
            if self.running:
                return False
            self.running = True
        try:
            while True:
                with self._state:
                    if not self._requested:
                        self.running = False
                        return True
                    self._requested = False
                if round_() is False:
                    return True
        finally:
            with self._state:
                self.running = False
