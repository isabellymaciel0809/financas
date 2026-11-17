# Avaliação do assistente: ollama · `qwen2.5:1.5b`

15 perguntas sobre o extrato de exemplo · 17.7 s por pergunta

| Métrica | Valor |
|---|---|
| **Respostas totalmente certas** | **80%** |
| Consulta certa | 87% |
| Valor certo na resposta | 80% |
| Sem valor inventado (checagem de fatos) | 100% |
| Sem frase errada sobre o período | 100% |

## Perguntas

| | Pergunta | Esperado | Problemas |
|---|---|---|---|
| ✅ | Quanto gastei este mês? | R$ 3.847,55 |  |
| ✅ | Quanto gastei com Uber nos últimos 3 meses? | R$ 208,84 |  |
| ✅ | Quanto gastei com alimentação no mês passado? | R$ 152,49 |  |
| ✅ | Quais foram meus 5 maiores gastos este mês? | R$ 1.800,00 |  |
| ✅ | Quanto sobrou de dinheiro no mês passado? | R$ 3.181,77 |  |
| ✅ | Quanto eu recebi este mês? | R$ 6.500,00 |  |
| ✅ | Quanto gastei no mercado em setembro? | R$ 396,25 |  |
| ✅ | Quanto paguei de Netflix nos últimos 3 meses? | R$ 134,70 |  |
| ✅ | Quanto gastei com transporte este mês? | R$ 274,28 |  |
| ✅ | Quanto gastei no iFood no mês passado? | R$ 123,59 |  |
| ✅ | Quanto gastei por mês nos últimos 3 meses? | R$ 3.847,55 |  |
| ❌ | Eu gastei mais em qual mes comparado com novembro? | R$ 4.555,68 | consulta, valor |
| ❌ | quais gastos vc acha q foi a mais que mes passado? | R$ 1.426,47 | valor |
| ❌ | Qual foi a coisa mais cara que comprei esse mes? | R$ 1.800,00 | consulta, valor |
| ✅ | Qual vai ser a previsão do tempo amanhã? | — |  |

## Respostas com problema

**Eu gastei mais em qual mes comparado com novembro?**

- Consultas: `[{"ferramenta": "evolucao_mensal", "argumentos": {"meses": 1}}]`
- Resposta: Em novembro, você gastou mais do que em qualquer outro mês.

**quais gastos vc acha q foi a mais que mes passado?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"mes": "mes_passado", "periodo": "mes_passado"}}]`
- Resposta: No período de 1º de outubro de 2026 a 11 de novembro de 2026, o gasto foi de R$ 4.555,68, enquanto no período comparado de 1º de janeiro de 2026 a 31 de outubro de 2026, o gasto foi de R$ 3.847,55. Isso resulta em uma diminuição de R$ 708,13. As categorias que tiveram maior aumento de gastos foram Compras, com um aumento de R$ 1.353,87.

**Qual foi a coisa mais cara que comprei esse mes?**

- Consultas: `[]`
- Resposta: A ferramenta não encontrou informações sobre o período especificado.

