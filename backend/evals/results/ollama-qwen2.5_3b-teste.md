# Avaliação da categorização: ollama · `qwen2.5:3b`

Conjunto `teste.csv` · 61 transações rotuladas · tempo total 168.76s

| Métrica | Valor |
|---|---|
| Acerto de ponta a ponta | **82.0%** |
| Taxa de automação (não ficou pendente) | 100.0% |
| Regras: cobertura | 49.2% |
| Regras: acerto quando aplicadas | 100.0% |
| LLM: transações recebidas | 31 |
| LLM: acerto sobre o que as regras não resolveram | 64.5% |
| LLM: acerto com confiança ≥ 60% | 64.5% |
| LLM: acerto com confiança < 60% (0 casos) | — |

## Erros

| Etapa | Descrição | Esperado | Previsto |
|---|---|---|---|
| llm | MADERO CONTAINER | Alimentação | Mercado |
| llm | MERCADINHO DONA ROSA | Mercado | Moradia |
| llm | OFICINA MECANICA DO TONINHO | Transporte | Saúde |
| llm | INDRIVER *VIAGEM | Transporte | Compras |
| llm | LEROY MERLIN | Moradia | Impostos e taxas |
| llm | SANEPAR | Contas e serviços | Impostos e taxas |
| llm | ULTRAGAZ | Contas e serviços | Impostos e taxas |
| llm | DESCOMPLICA | Educação | Saúde |
| llm | NINTENDO ESHOP | Lazer | Compras |
| llm | CASAS BAHIA | Compras | Mercado |
| llm | Estorno - NETSHOES | Compras | Outros |

## Confusões mais comuns

- Contas e serviços → Impostos e taxas: 2
- Alimentação → Mercado: 1
- Mercado → Moradia: 1
- Transporte → Saúde: 1
- Transporte → Compras: 1
