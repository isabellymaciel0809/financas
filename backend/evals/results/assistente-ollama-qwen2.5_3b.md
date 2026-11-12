# Avaliação do assistente: ollama · `qwen2.5:3b`

12 perguntas sobre o extrato de exemplo · 37.6 s por pergunta

| Métrica | Valor |
|---|---|
| **Respostas totalmente certas** | **75%** |
| Consulta certa | 92% |
| Valor certo na resposta | 92% |
| Sem valor inventado (checagem de fatos) | 92% |
| Sem frase errada sobre o período | 83% |

## Perguntas

| | Pergunta | Esperado | Problemas |
|---|---|---|---|
| ✅ | Quanto gastei este mês? | R$ 3.847,55 |  |
| ❌ | Quanto gastei com Uber nos últimos 3 meses? | R$ 208,84 | frase |
| ✅ | Quanto gastei com alimentação no mês passado? | R$ 152,49 |  |
| ✅ | Quais foram meus 5 maiores gastos este mês? | R$ 1.800,00 |  |
| ✅ | Quanto sobrou de dinheiro no mês passado? | R$ 3.181,77 |  |
| ✅ | Quanto eu recebi este mês? | R$ 6.500,00 |  |
| ✅ | Quanto gastei no mercado em setembro? | R$ 396,25 |  |
| ❌ | Quanto paguei de Netflix nos últimos 3 meses? | R$ 134,70 | frase |
| ✅ | Quanto gastei com transporte este mês? | R$ 274,28 |  |
| ✅ | Quanto gastei no iFood no mês passado? | R$ 123,59 |  |
| ❌ | Quanto gastei por mês nos últimos 3 meses? | R$ 3.847,55 | consulta, valor, valor inventado |
| ✅ | Qual vai ser a previsão do tempo amanhã? | — |  |

## Respostas com problema

**Quanto gastei com Uber nos últimos 3 meses?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"periodo": "ultimos_3_meses", "estabelecimento": "uber"}}]`
- Resposta: No último mês, você gastou R$ 208,84 no Uber. As maiores despesas foram em 26/10/2026, 03/09/2026, 25/10/2026, 05/11/2026 e 25/09/2026.

**Quanto paguei de Netflix nos últimos 3 meses?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"mes": "2026-10", "periodo": "ultimos_3_meses", "categoria": "Netflix"}}]`
- Resposta: No último mês, paguei R$ 134,70 de Netflix. As maiores despesas foram em 10/09/2026, 10/10/2026 e 10/11/2026, todas no valor de R$ 44,90. Todas essas despesas estão na categoria Assinaturas.

**Quanto gastei por mês nos últimos 3 meses?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"periodo": "ultimos_3_meses"}}]`
- Resposta: No último mês, gastei R$ 2.040,20 em moradia, R$ 587,65 em alimentação e R$ 890,50 em viagem. As maiores despesas foram pagamentos de aluguel no valor de R$ 1.800,00.

