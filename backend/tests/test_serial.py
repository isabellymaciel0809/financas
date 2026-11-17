"""Filas em segundo plano: uma execução por vez, e nenhum pedido se perde."""

import threading
import time

import pytest

from app.services.serial import SerialRunner


def _in_thread(runner: SerialRunner, round_) -> threading.Thread:
    thread = threading.Thread(target=runner.trigger, args=(round_,))
    thread.start()
    return thread


def test_pedido_durante_a_execucao_vira_mais_uma_rodada():
    runner = SerialRunner()
    rounds = []
    inside, go_on = threading.Event(), threading.Event()

    def round_():
        rounds.append(threading.current_thread().name)
        inside.set()
        go_on.wait(5)

    first = _in_thread(runner, round_)
    inside.wait(5)
    assert runner.trigger(round_) is False  # já está rodando: só deixa o pedido
    go_on.set()
    first.join(5)

    assert len(rounds) == 2
    assert len(set(rounds)) == 1  # as duas rodadas na thread que já estava rodando
    assert not runner.running


def test_pedido_que_chega_quando_a_rodada_termina_nao_se_perde():
    # A janela da versão antiga: a rodada acabou de terminar e a execução vai conferir se
    # chegou pedido novo. Um pedido chega exatamente aí. Seja qual for a ordem, ele é atendido.
    runner = SerialRunner()
    rounds = []
    finishing = threading.Event()

    def round_():
        rounds.append(1)
        if len(rounds) == 1:
            runner._state.acquire()  # segura a execução logo antes da conferência
            finishing.set()

    first = _in_thread(runner, round_)
    finishing.wait(5)
    late = _in_thread(runner, round_)
    time.sleep(0.05)  # o pedido tardio fica parado no mesmo lock
    runner._state.release()
    first.join(5)
    late.join(5)

    assert len(rounds) == 2
    assert not runner.running


def test_rodada_que_pede_para_parar_encerra_a_execucao():
    runner = SerialRunner()
    rounds = []

    def round_():
        rounds.append(1)
        runner.trigger(round_)  # chega um pedido, mas a rodada manda parar (ex.: LLM fora do ar)
        return False

    assert runner.trigger(round_) is True
    assert len(rounds) == 1
    assert not runner.running


def test_erro_na_rodada_libera_a_fila():
    runner = SerialRunner()

    def broken():
        raise RuntimeError("falhou")

    with pytest.raises(RuntimeError):
        runner.trigger(broken)
    assert not runner.running
    assert runner.trigger(lambda: None) is True
