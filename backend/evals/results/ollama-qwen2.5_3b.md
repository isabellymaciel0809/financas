# Avaliação da categorização: ollama · `qwen2.5:3b`

Conjunto `dataset.csv` · 153 transações rotuladas · tempo total 354.26s

| Métrica | Valor |
|---|---|
| Acerto de ponta a ponta | **88.2%** |
| Taxa de automação (não ficou pendente) | 97.4% |
| Regras: cobertura | 69.3% |
| Regras: acerto quando aplicadas | 100.0% |
| LLM: transações recebidas | 47 |
| LLM: acerto sobre o que as regras não resolveram | 61.7% |
| LLM: acerto com confiança ≥ 60% | 70.7% |
| LLM: acerto com confiança < 60% (2 casos) | 0.0% |

## Erros

| Etapa | Descrição | Esperado | Previsto |
|---|---|---|---|
| llm | DIA BRASIL SOCIEDADE LTDA | Mercado | Alimentação |
| llm | ZUL DIGITAL | Transporte | Mercado |
| llm | Pagamento de boleto - IMOBILIARIA CENTRAL | Moradia | Contas e serviços |
| llm | TIM S A | Contas e serviços | Mercado |
| llm | LIGHT SERVICOS DE ELETRICIDADE | Contas e serviços | Moradia |
| llm | TOTALPASS | Saúde | Assinaturas |
| llm | ESTANTE VIRTUAL | Educação | Cuidados pessoais |
| llm | EVENTIM BRASIL | Lazer | Viagem |
| llm | BUSER | Viagem | Outros |
| llm | SAQUE BANCO24HORAS | Outros | Saúde |
| llm | SAQUE CAIXA ELETRONICO | Outros | Saúde |
| llm | MERCADO LIVRE VENDA | Renda extra | Compras |
| llm | Estorno - IFD*IFOOD | Alimentação | Outros |
| llm | Estorno - AMAZON MARKETPLACE | Compras | Outros |

## Confusões mais comuns

- Outros → Saúde: 2
- Mercado → Alimentação: 1
- Transporte → Mercado: 1
- Moradia → Contas e serviços: 1
- Contas e serviços → Mercado: 1
