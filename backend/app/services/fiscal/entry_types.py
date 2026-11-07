"""Coluna "Tipo" da planilha da empresa."""

# Sugestões exibidas na interface; o campo aceita outros valores ("e afins").
ENTRY_TYPES = ["Custo", "Despesas", "Estoque", "Receita", "Caixa"]
INCOME_TYPES = {"Receita"}


def default_entry_type(proposal: str | None) -> str:
    """Gasto ligado a uma proposta/obra é custo dela; sem proposta é despesa geral."""
    return "Custo" if proposal else "Despesas"
