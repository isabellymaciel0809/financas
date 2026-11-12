# Avaliação do assistente: ollama · `qwen2.5:3b` · conjunto de teste

9 perguntas sobre o extrato de exemplo · 26.5 s por pergunta

| Métrica | Valor |
|---|---|
| **Respostas totalmente certas** | **67%** |
| Consulta certa | 67% |
| Valor certo na resposta | 67% |
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

## Respostas com problema

**Qual foi a coisa mais cara que comprei esse mes?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"periodo": "este_mes", "limite": 1, "categoria": "Compras"}}]`
- Resposta: Você gastou mais dinheiro comprando no débito na AMAZON MARKETPLACE no dia 09/11/2026, no valor de R$ 1.299,00.

**Eu gastei mais em qual mes comparado com novembro?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"periodo": "novembro", "mes": null, "limite": 5}}]`
- Resposta: Em novembro de 2026, você gastou mais em Moradia, com um total de R$ 1.800,00. As maiores despesas foram pagamentos de aluguel e compras no débito.

**quais gastos vc acha q foi a mais que mes passado?**

- Consultas: `[{"ferramenta": "gastos", "argumentos": {"estabelecimento": "", "limite": 1, "periodo": "mes_passado", "mes": "2026-10", "categoria": ""}}]`
- Resposta: No mês passado, o maior gasto foi R$ 1.800,00 em Moradia.

