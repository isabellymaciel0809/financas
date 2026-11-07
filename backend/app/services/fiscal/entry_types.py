"""Coluna "Tipo" da planilha da empresa.

Os nomes seguem a lista de validação da planilha real "DRE-FLUXO DE CAIXA": as fórmulas do DRE
somam por esses textos exatos (ex.: SUMIFS(...; "Despesa")), então "Despesas" no plural não
entraria na conta.
"""

# Sugestões exibidas na interface; o campo aceita outros valores.
ENTRY_TYPES = ["Custo", "Despesa", "Estoque", "Receita", "Caixa", "Bens", "Diaria", "Dedução"]
INCOME_TYPES = {"Receita"}
# Linha da planilha sem Tipo: a planilha não a conta em nenhum total, então o sistema também não.
MISSING_TYPE = "Sem tipo"
# Linhas de controle da planilha e linhas sem tipo: não são entradas nem saídas.
NEUTRAL_TYPES = {"Saldo inicial", "Saldo final", MISSING_TYPE}


def default_entry_type(proposal: str | None) -> str:
    """Gasto ligado a uma proposta/obra é custo dela; sem proposta é despesa geral."""
    return "Custo" if proposal else "Despesa"
