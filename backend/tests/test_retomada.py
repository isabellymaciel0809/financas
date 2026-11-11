"""Retomada das filas ao iniciar: o que estava pela metade quando o servidor parou continua."""

from datetime import date

from fastapi.testclient import TestClient

from app import main
from app.config import get_settings
from app.models import CategorizedBy, Expense, ExpenseSource, ExpenseStatus, Transaction
from app.services.background import resume_pending_work
from app.services.fiscal.processor import upload_dir
from app.services.text import merchant_key
from tests.conftest import FakeLLM
from tests.test_fiscal import make_nfe_xml


def _left_behind(db) -> tuple[int, int]:
    """Estado de um servidor que caiu: uma nota em "Processando" e uma transação sem categoria."""
    (upload_dir() / "parada.xml").write_bytes(make_nfe_xml(freight="0.00"))
    expense = Expense(
        source=ExpenseSource.nfe_xml,
        status=ExpenseStatus.processing,
        original_filename="nota.xml",
        stored_filename="parada.xml",
        issues=[],
    )
    description = "Pix enviado - Maria Oliveira"  # nenhuma regra resolve: só a LLM
    tx = Transaction(
        date=date(2026, 10, 1),
        description=description,
        amount_cents=-5000,
        merchant_key=merchant_key(description),
        fingerprint="retomada",
    )
    db.add_all([expense, tx])
    db.commit()
    return expense.id, tx.id


def test_retoma_nota_e_transacao_que_ficaram_paradas(db):
    expense_id, tx_id = _left_behind(db)

    resume_pending_work(FakeLLM({"maria": ("Lazer", 0.9)}))

    db.expire_all()
    expense = db.get(Expense, expense_id)
    assert expense.status != ExpenseStatus.processing
    assert expense.total_cents == 5330
    tx = db.get(Transaction, tx_id)
    assert tx.categorized_by == CategorizedBy.llm
    assert tx.category.name == "Lazer"


def test_sem_llm_retoma_as_notas_e_deixa_as_transacoes_pendentes(db):
    expense_id, tx_id = _left_behind(db)

    resume_pending_work(None)

    db.expire_all()
    assert db.get(Expense, expense_id).status != ExpenseStatus.processing
    assert db.get(Transaction, tx_id).categorized_by == CategorizedBy.none


def test_llm_fora_do_ar_nao_derruba_a_retomada(db):
    expense_id, tx_id = _left_behind(db)

    resume_pending_work(FakeLLM(fail=True))

    db.expire_all()
    assert db.get(Expense, expense_id).status != ExpenseStatus.processing
    assert db.get(Transaction, tx_id).categorized_by == CategorizedBy.none


def test_servidor_dispara_a_retomada_ao_iniciar(db, monkeypatch):
    started = []
    monkeypatch.setattr(get_settings(), "resume_queues_on_startup", True)
    monkeypatch.setattr(main, "resume_in_background", started.append)

    with TestClient(main.app):
        pass

    assert len(started) == 1
