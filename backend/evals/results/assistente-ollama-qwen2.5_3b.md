# Avaliação do assistente: ollama · `qwen2.5:3b`

15 perguntas sobre o extrato de exemplo · 41.0 s por pergunta

| Métrica | Valor |
|---|---|
| **Respostas totalmente certas** | **93%** |
| Consulta certa | 93% |
| Valor certo na resposta | 93% |
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
| ✅ | Eu gastei mais em qual mes comparado com novembro? | R$ 4.555,68 |  |
| ✅ | quais gastos vc acha q foi a mais que mes passado? | R$ 1.426,47 |  |
| ❌ | Qual foi a coisa mais cara que comprei esse mes? | R$ 1.800,00 | consulta, valor |
| ✅ | Qual vai ser a previsão do tempo amanhã? | — |  |

## Respostas com problema

**Qual foi a coisa mais cara que comprei esse mes?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"periodo": "este_mes", "limite": 1, "categoria": "Compras"}}]`
- Resposta: No mês de novembro de 2026, a maior despesa em compras foi no dia 09/11/2026 no valor de R$ 1.299,00.

