# Avaliação do assistente: ollama · `qwen2.5:1.5b` · conjunto de teste

9 perguntas sobre o extrato de exemplo · 17.0 s por pergunta

| Métrica | Valor |
|---|---|
| **Respostas totalmente certas** | **67%** |
| Consulta certa | 67% |
| Valor certo na resposta | 67% |
| Sem valor inventado (checagem de fatos) | 89% |
| Sem frase errada sobre o período | 100% |

## Perguntas

| | Pergunta | Esperado | Problemas |
|---|---|---|---|
| ✅ | Quanto eu paguei de aluguel esse mes? | R$ 1.800,00 |  |
| ❌ | Qual o meu maior gasto recorrente? | R$ 1.800,00 | consulta, valor |
| ✅ | Quanto eu pago de Netflix? | R$ 44,90 |  |
| ✅ | Quanto entrou de salario esse mes? | R$ 6.500,00 |  |
| ✅ | qto tive de receita esse mes contando salario, freela, e pagamento de emprestimos? | R$ 6.500,00 |  |
| ✅ | qto gastei de petshop? | — |  |
| ❌ | qual é a media de gasto mensal a partir de setembro até novembro | R$ 4.087,07 | consulta, valor, valor inventado |
| ❌ | quanto eu gastei com uber nos ultimos 2 meses? | R$ 143,63 | consulta, valor |
| ✅ | quanto eu gastei com lazer nos ultimos 3 meses meses? | R$ 133,52 |  |

## Respostas com problema

**Qual o meu maior gasto recorrente?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"categoria": "Alimentação", "limite": 5, "mes": "2026-11"}}]`
- Resposta: O maior gasto recorrente foi em compras no débito na categoria Alimentação. As duas maiores despesas foram em 4 de novembro e 2 de novembro, respectivamente. A compra no débito na Padaria Bella Vista foi de R$ 12,83 e a no débito na IFD IFOOD foi de R$ 29,68.

**qual é a media de gasto mensal a partir de setembro até novembro**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"mes": "2026-10", "periodo": "ultimos_3_meses"}}]`
- Resposta: A média mensal de gasto entre setembro e novembro de 2026 foi de R$ 1.852,36. As maiores despesas foram: Pagamento de boleto - Aluguel Imobiliária Lar (R$ 1.800,00), compra no débito - LATAM AIRLINES (R$ 890,50), compra no débito - CARREFOUR HIPER (R$ 217,32), Pix enviado - Maria Oliveira Souza (R$ 204,63), e compra no débito - POSTO SHELL (R$ 189,49).

**quanto eu gastei com uber nos ultimos 2 meses?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"estabelecimento": "uber", "mes": "ultimos_2_meses"}}]`
- Resposta: Desculpe, mas parece que houve um erro na sua pergunta. Você quis dizer "últimos 2 meses" ou "ultimos_2_meses"? Por favor, tente novamente.

