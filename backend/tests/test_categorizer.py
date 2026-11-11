from datetime import date

import pytest
from sqlalchemy import select

from app.models import CategorizedBy, Category, Transaction
from app.services.categorizer.pipeline import categorize_transactions, remember
from app.services.categorizer.rules import match_rule
from app.services.fiscal.items import categorize_items
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
        # Cuidados pessoais: antes, barbearia ia para a LLM, que chutava "Lazer" ou "Outros".
        ("Compra no débito - SumUp *BARBEARIA DO ZE", -5000, "Cuidados pessoais"),
        ("CLINICA DE ESTETICA AURORA", -18000, "Cuidados pessoais"),  # vence "clinica" (Saúde)
        ("O BOTICARIO", -8990, "Cuidados pessoais"),
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
    remember(db, merchant_key("ATELIE DONA RITA"), lazer.id)
    llm = FakeLLM({"maria": ("Transferências", 0.7)})

    txs = [
        _tx(db, "SumUp *ATELIE DONA RITA", -5000),  # memória
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
    llm = FakeLLM({"atelie": ("Lazer", 0.7)})
    txs = [_tx(db, "SumUp *ATELIE DONA RITA", -4500 - i) for i in range(3)]
    estorno = _tx(db, "SumUp *ATELIE DONA RITA", 4500)  # sinal diferente: pergunta separada
    result = categorize_transactions(db, [*txs, estorno], llm)

    assert [i.description for i in llm.calls[0]] == ["SumUp *ATELIE DONA RITA"] * 2
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


# --- Pessoal x empresa -----------------------------------------------------------------------
# Com as categorias de empresa na lista do extrato, o acerto da LLM na avaliação caiu de 62%
# para 51% ("Venda OLX" virava "Receita de vendas", "SAQUE" virava "Fretes e entregas").
# Estes testes rodam no CI, onde não há LLM, e impedem que a mistura volte.

COMPANY_ONLY = {"Receita de vendas", "Receita de serviços", "Fretes e entregas"}
PERSONAL_ONLY = {"Salário", "Renda extra", "Rendimentos", "Cuidados pessoais"}


def test_llm_do_extrato_so_ve_categorias_pessoais(db):
    llm = FakeLLM()
    categorize_transactions(db, [_tx(db, "Pix recebido - Venda OLX", 15000)], llm)
    offered = set(llm.offered)
    assert offered & COMPANY_ONLY == set()
    assert PERSONAL_ONLY | {"Alimentação", "Outros"} <= offered


def test_extrato_descarta_categoria_de_empresa_vinda_da_llm(db):
    tx = _tx(db, "SAQUE BANCO24HORAS", -20000)
    categorize_transactions(db, [tx], FakeLLM({"saque": ("Fretes e entregas", 0.9)}))
    assert tx.categorized_by == CategorizedBy.none


def test_regra_de_empresa_nao_vale_no_extrato(db):
    # "correios" é regra de "Fretes e entregas" (itens de nota); no extrato fica para a LLM.
    assert match_rule("CORREIOS AGENCIA CENTRO", -3500) == "Fretes e entregas"
    tx = _tx(db, "CORREIOS AGENCIA CENTRO", -3500)
    categorize_transactions(db, [tx], None)
    assert tx.categorized_by == CategorizedBy.none


def test_llm_dos_itens_de_nota_ve_categorias_de_empresa(db):
    from app.models import ExpenseItem

    llm = FakeLLM()
    item = ExpenseItem(position=1, description="PECA XPTO 3/4", total_cents=1990)
    categorize_items(db, [item], llm)
    offered = set(llm.offered)
    assert {"Fretes e entregas", "Materiais e manutenção", "Alimentação"} <= offered
    assert offered & PERSONAL_ONLY == set()
