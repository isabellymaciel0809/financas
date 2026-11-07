"""Coluna "Tipo" da planilha da empresa.

Os nomes seguem a lista de validação da planilha real "DRE-FLUXO DE CAIXA": as fórmulas do DRE
somam por esses textos exatos (ex.: SUMIFS(...; "Despesa")), então "Despesas" no plural não
entraria na conta.
"""

# Sugestões exibidas na interface; o campo aceita outros valores.
ENTRY_TYPES = ["Custo", "Despesa", "Estoque", "Receita", "Caixa", "Bens", "Diaria", "Dedução"]
INCOME_TYPES = {"Receita"}
# Linhas de controle da planilha: não são entradas nem saídas.
NEUTRAL_TYPES = {"Saldo inicial", "Saldo final"}


def default_entry_type(proposal: str | None) -> str:
    """Gasto ligado a uma proposta/obra é custo dela; sem proposta é despesa geral."""
    return "Custo" if proposal else "Despesa"
