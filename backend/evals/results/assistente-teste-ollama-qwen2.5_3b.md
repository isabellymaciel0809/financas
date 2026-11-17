# Avaliação do assistente: ollama · `qwen2.5:3b` · conjunto de teste

9 perguntas sobre o extrato de exemplo · 33.4 s por pergunta

| Métrica | Valor |
|---|---|
| **Respostas totalmente certas** | **78%** |
| Consulta certa | 78% |
| Valor certo na resposta | 78% |
| Sem valor inventado (checagem de fatos) | 100% |
| Sem frase errada sobre o período | 100% |

## Perguntas

| | Pergunta | Esperado | Problemas |
|---|---|---|---|
| ✅ | Quanto eu paguei de aluguel esse mes? | R$ 1.800,00 |  |
| ✅ | Qual o meu maior gasto recorrente? | R$ 1.800,00 |  |
| ✅ | Quanto eu pago de Netflix? | R$ 44,90 |  |
| ✅ | Quanto entrou de salario esse mes? | R$ 6.500,00 |  |
| ✅ | qto tive de receita esse mes contando salario, freela, e pagamento de emprestimos? | R$ 6.500,00 |  |
| ✅ | qto gastei de petshop? | — |  |
| ❌ | qual é a media de gasto mensal a partir de setembro até novembro | R$ 4.087,07 | consulta, valor |
| ❌ | quanto eu gastei com uber nos ultimos 2 meses? | R$ 143,63 | consulta, valor |
| ✅ | quanto eu gastei com lazer nos ultimos 3 meses meses? | R$ 133,52 |  |

## Respostas com problema

**qual é a media de gasto mensal a partir de setembro até novembro**

- Consultas: `[{"ferramenta": "resumo_financeiro", "argumentos": {"mes": "2026-10", "meses": 3, "periodo": "este_mes"}}]`
- Resposta: Para calcular a média mensal de gastos entre setembro e novembro, precisamos obter os dados para setembro, outubro e novembro. Infelizmente, a ferramenta não forneceu esses dados diretamente. Você pode usar a mesma ferramenta para obter os valores para esses meses específicos.

**quanto eu gastei com uber nos ultimos 2 meses?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"categoria": "Transporte", "periodo": "ultimos_2_meses"}}]`
- Resposta: Não foi possível encontrar os gastos com Uber nos últimos 2 meses. Tente novamente com um período válido.

