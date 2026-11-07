from app.services.categorizer.llm import (
    CategoryOption,
    LLMItem,
    build_user_message,
    categorization_schema,
)


def test_mensagem_descreve_categorias_e_sinal_por_extenso():
    text = build_user_message(
        [LLMItem(0, "PARAMOUNT+", -1990), LLMItem(1, "Pix recebido - Cliente", 123456)],
        [
            CategoryOption("Assinaturas", "expense", "streaming"),
            CategoryOption("Renda extra", "income"),
        ],
    )
    assert "- Assinaturas (saída): streaming" in text
    assert "- Renda extra (entrada)" in text
    assert '0. "PARAMOUNT+" (saída de R$ 19,90)' in text
    assert '1. "Pix recebido - Cliente" (entrada de R$ 1.234,56)' in text


def test_schema_restringe_categorias():
    schema = categorization_schema(["Mercado", "Outros"])
    item = schema["properties"]["results"]["items"]
    assert item["properties"]["category"]["enum"] == ["Mercado", "Outros"]
