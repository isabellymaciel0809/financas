# Avaliação da categorização: ollama · `qwen2.5:3b`

145 transações rotuladas · tempo total 257.25s

| Métrica | Valor |
|---|---|
| Acerto de ponta a ponta | **88.3%** |
| Taxa de automação (não ficou pendente) | 98.6% |
| Regras: cobertura | 69.0% |
| Regras: acerto quando aplicadas | 100.0% |
| LLM: transações recebidas | 45 |
| LLM: acerto sobre o que as regras não resolveram | 62.2% |
| LLM: acerto com confiança ≥ 60% | 65.1% |
| LLM: acerto com confiança < 60% (0 casos) | — |

## Erros

| Etapa | Descrição | Esperado | Previsto |
|---|---|---|---|
| llm | DIA BRASIL SOCIEDADE LTDA | Mercado | Alimentação |
| llm | ZUL DIGITAL | Transporte | Mercado |
| llm | Pagamento de boleto - IMOBILIARIA CENTRAL | Moradia | Contas e serviços |
| llm | TIM S A | Contas e serviços | Mercado |
| llm | LIGHT SERVICOS DE ELETRICIDADE | Contas e serviços | Moradia |
| llm | OI FIBRA | Contas e serviços | Assinaturas |
| llm | TOTALPASS | Saúde | Assinaturas |
| llm | ESTANTE VIRTUAL | Educação | Outros |
| llm | EVENTIM BRASIL | Lazer | Educação |
| llm | CENTAURO | Compras | Outros |
| llm | MERCADO PAGO *LOJADOJOAO | Compras | Mercado |
| llm | BUSER | Viagem | Outros |
| llm | MERCADO LIVRE VENDA | Renda extra | Compras |
| llm | Estorno - IFD*IFOOD | Alimentação | Transferências |
| llm | Estorno - AMAZON MARKETPLACE | Compras | Transferências |

## Confusões mais comuns

- Mercado → Alimentação: 1
- Transporte → Mercado: 1
- Moradia → Contas e serviços: 1
- Contas e serviços → Mercado: 1
- Contas e serviços → Moradia: 1
