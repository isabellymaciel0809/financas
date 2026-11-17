# Avaliação do assistente: ollama · `qwen2.5:3b` · conjunto de teste

12 perguntas sobre o extrato de exemplo · 37.3 s por pergunta

| Métrica | Valor |
|---|---|
| **Respostas totalmente certas** | **58%** |
| Consulta certa | 58% |
| Valor certo na resposta | 58% |
| Sem valor inventado (checagem de fatos) | 100% |
| Sem frase errada sobre o período | 100% |

## Perguntas

| | Pergunta | Esperado | Problemas |
|---|---|---|---|
| ❌ | Qual foi a coisa mais cara que comprei esse mes? | R$ 1.800,00 | consulta, valor |
| ✅ | Quanto eu paguei de aluguel esse mes? | R$ 1.800,00 |  |
| ✅ | Qual o meu maior gasto recorrente? | R$ 1.800,00 |  |
| ✅ | Quanto eu pago de Netflix? | R$ 44,90 |  |
| ✅ | Quanto entrou de salario esse mes? | R$ 6.500,00 |  |
| ❌ | Eu gastei mais em qual mes comparado com novembro? | R$ 4.555,68 | consulta, valor |
| ✅ | qto tive de receita esse mes contando salario, freela, e pagamento de emprestimos? | R$ 6.500,00 |  |
| ❌ | quais gastos vc acha q foi a mais que mes passado? | R$ 1.426,47 | consulta, valor |
| ✅ | qto gastei de petshop? | — |  |
| ❌ | qual é a media de gasto mensal a partir de setembro até novembro | R$ 4.087,07 | consulta, valor |
| ❌ | quanto eu gastei com uber nos ultimos 2 meses? | R$ 143,63 | consulta, valor |
| ✅ | quanto eu gastei com lazer nos ultimos 3 meses meses? | R$ 133,52 |  |

## Respostas com problema

**Qual foi a coisa mais cara que comprei esse mes?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"periodo": "este_mes", "limite": 1, "categoria": "Compras"}}]`
- Resposta: Você gastou mais dinheiro comprando no débito na AMAZON MARKETPLACE no dia 09/11/2026, no valor de R$ 1.299,00.

**Eu gastei mais em qual mes comparado com novembro?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"periodo": "novembro", "mes": null, "limite": 5}}]`
- Resposta: Em novembro de 2026, você gastou mais em Moradia, com um total de R$ 1.800,00. As maiores despesas foram pagamentos de aluguel e compras no débito.

**quais gastos vc acha q foi a mais que mes passado?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"mes": "2026-10", "categoria": "", "estabelecimento": "", "limite": 1, "periodo": "mes_passado"}}]`
- Resposta: No mês passado, o maior gasto foi R$ 1.800,00 em Moradia.

**qual é a media de gasto mensal a partir de setembro até novembro**

- Consultas: `[{"ferramenta": "resumo_financeiro", "argumentos": {"periodo": "este_mes", "mes": "2026-10", "meses": 3}}]`
- Resposta: Para calcular a média mensal de gastos entre setembro e novembro, precisamos primeiro obter os gastos de setembro e outubro. Infelizmente, os dados fornecidos não incluem os gastos de setembro. Podemos apenas analisar os dados de outubro e novembro.  Gastos em outubro: R$ 4.555,68 Gastos em novembro: R$ 4.555,68  A média mensal de gastos entre setembro e novembro é de R$ 4.555,68.

**quanto eu gastei com uber nos ultimos 2 meses?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"periodo": "ultimos_2_meses", "estabelecimento": "uber"}}]`
- Resposta: Desculpe, parece que houve um erro. Você deve fornecer um período válido como 'este_mes', 'mes_passado', 'ultimos_3_meses', 'ultimos_6_meses', 'este_ano' ou 'tudo'. Tente novamente.

