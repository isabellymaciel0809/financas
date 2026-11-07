from datetime import date

import pytest
from sqlalchemy import select

from app.models import CategorizedBy, Category, Transaction
from app.services.categorizer.pipeline import categorize_transactions, remember
from app.services.categorizer.rules import match_rule
from app.services.text import merchant_key
from tests.conftest import FakeLLM


@pytest.mark.parametrize(
    ("description", "amount", "expected"),
    [
        ("Compra no débito - IFD*IFOOD", -4590, "Alimentação"),
        ("UBER *TRIP HELP.UBER.COM", -2300, "Transporte"),
        ("Compra no débito - 99APP *99POP", -1500, "Transporte"),
        ("Pão de Açúcar Loja 123", -15000, "Mercado"),
        ("Transferência recebida - Salário ACME", 650000, "Salário"),
        ("Pix enviado - Padaria das Flores", -1200, "Alimentação"),  # "das" não é imposto
        ("Pix enviado - Maria Oliveira", -5000, None),
        # Regressões encontradas pela avaliação (evals/):
        ("UBER EATS", -4870, "Alimentação"),  # frase mais longa vence "uber"
        ("MERCADO PAGO *LOJADOJOAO", -7500, None),  # intermediador não é supermercado
        ("MERCADO PAGO *ACADEMIA FORMA", -9900, "Saúde"),
        ("Salário devolvido", -1000, None),  # regra de receita não vale para saída
    ],
)
def test_regras(description, amount, expected):
    assert match_rule(description, amount) == expected


def test_merchant_key_ignora_ruido():
    assert merchant_key("COMPRA CARTAO IFD*IFOOD 12/10") == "ifd ifood"
    assert merchant_key("Pix enviado - Padaria Pão Quente Ltda") == "padaria pao quente"


def _tx(db, description, amount):
    tx = Transaction(
        date=date(2026, 10, 1),
        description=description,
        amount_cents=amount,
        merchant_key=merchant_key(description),
        fingerprint=description + str(amount),
    )
    db.add(tx)
    db.flush()
    return tx


def _category(db, name):
    return db.scalar(select(Category).where(Category.name == name))


def test_cascata_memoria_regra_llm(db):
    lazer = _category(db, "Lazer")
    remember(db, merchant_key("BARBEARIA DO ZE"), lazer.id)
    llm = FakeLLM({"maria": ("Transferências", 0.7)})

    txs = [
        _tx(db, "SumUp *BARBEARIA DO ZE", -5000),  # memória
        _tx(db, "IFD*IFOOD", -4000),  # regra
        _tx(db, "Pix enviado - Maria Oliveira", -10000),  # LLM
        _tx(db, "XPTO 123", -999),  # ninguém sabe
    ]
    result = categorize_transactions(db, txs, llm)

    assert [t.categorized_by for t in txs] == [
        CategorizedBy.memory,
        CategorizedBy.rule,
        CategorizedBy.llm,
        CategorizedBy.none,
    ]
    assert txs[0].category_id == lazer.id
    assert txs[2].category.name == "Transferências"
    assert txs[2].confidence == 0.7
    assert result.stats.model_dump() == {"memory": 1, "rule": 1, "llm": 1, "none": 1}
    # Só o que sobrou das etapas baratas foi enviado ao LLM.
    assert [i.description for i in llm.calls[0]] == ["Pix enviado - Maria Oliveira", "XPTO 123"]


def test_llm_categoria_inventada_e_descartada(db):
    llm = FakeLLM({"xpto": ("Categoria Que Nao Existe", 0.99)})
    tx = _tx(db, "XPTO", -100)
    result = categorize_transactions(db, [tx], llm)
    assert tx.categorized_by == CategorizedBy.none
    assert result.stats.none == 1


def test_llm_nao_pode_dar_categoria_de_receita_para_saida(db):
    tx = _tx(db, "Transferência para conta poupança", -50000)
    categorize_transactions(db, [tx], FakeLLM({"poupanca": ("Salário", 0.9)}))
    assert tx.categorized_by == CategorizedBy.none


def test_falha_do_llm_nao_quebra_importacao(db):
    tx = _tx(db, "XPTO", -100)
    result = categorize_transactions(db, [tx], FakeLLM(fail=True))
    assert tx.categorized_by == CategorizedBy.none
    assert result.llm_error == "LLM fora do ar"


def test_lotes(db):
    llm = FakeLLM({"loja": ("Compras", 0.9)})
    names = ["Aurora", "Bonita", "Central", "Dourada", "Estrela"]
    txs = [_tx(db, f"Loja {name}", -100 - i) for i, name in enumerate(names)]
    result = categorize_transactions(db, txs, llm, batch_size=2)
    assert len(llm.calls) == 3
    assert result.stats.llm == 5


def test_mesmo_estabelecimento_vai_uma_vez_so_para_a_llm(db):
    llm = FakeLLM({"barbearia": ("Lazer", 0.7)})
    txs = [_tx(db, "SumUp *BARBEARIA DO ZE", -4500 - i) for i in range(3)]
    estorno = _tx(db, "SumUp *BARBEARIA DO ZE", 4500)  # sinal diferente: pergunta separada
    result = categorize_transactions(db, [*txs, estorno], llm)

    assert [i.description for i in llm.calls[0]] == ["SumUp *BARBEARIA DO ZE"] * 2
    assert {i.amount_cents > 0 for i in llm.calls[0]} == {True, False}
    assert all(t.category.name == "Lazer" for t in txs)
    assert result.stats.llm == 4


def test_reaproveita_decisao_anterior_da_llm(db):
    first = _tx(db, "Pix enviado - Maria Oliveira", -10000)
    categorize_transactions(db, [first], FakeLLM({"maria": ("Transferências", 0.8)}))

    llm = FakeLLM()
    later = _tx(db, "Pix enviado - Maria Oliveira", -25000)
    result = categorize_transactions(db, [later], llm)

    assert llm.calls == []  # nem chegou a chamar o modelo
    assert later.category.name == "Transferências"
    assert later.categorized_by == CategorizedBy.llm
    assert result.stats.llm == 1


def test_transacao_manual_nao_e_sobrescrita(db):
    tx = _tx(db, "IFD*IFOOD", -4000)
    tx.categorized_by = CategorizedBy.manual
    tx.category_id = _category(db, "Lazer").id
    categorize_transactions(db, [tx], None)
    assert tx.category.name == "Lazer"
