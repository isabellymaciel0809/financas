# Avaliação da categorização: ollama · `qwen2.5:3b`

Conjunto `teste.csv` · 67 transações rotuladas · tempo total 246.06s

| Métrica | Valor |
|---|---|
| Acerto de ponta a ponta | **82.1%** |
| Taxa de automação (não ficou pendente) | 100.0% |
| Regras: cobertura | 49.3% |
| Regras: acerto quando aplicadas | 100.0% |
| LLM: transações recebidas | 34 |
| LLM: acerto sobre o que as regras não resolveram | 64.7% |
| LLM: acerto com confiança ≥ 60% | 64.7% |
| LLM: acerto com confiança < 60% (0 casos) | — |

## Erros

| Etapa | Descrição | Esperado | Previsto |
|---|---|---|---|
| llm | MADERO CONTAINER | Alimentação | Moradia |
| llm | OFICINA MECANICA DO TONINHO | Transporte | Contas e serviços |
| llm | INDRIVER *VIAGEM | Transporte | Alimentação |
| llm | LEROY MERLIN | Moradia | Mercado |
| llm | SANEPAR | Contas e serviços | Impostos e taxas |
| llm | ULTRAGAZ | Contas e serviços | Impostos e taxas |
| llm | DESCOMPLICA | Educação | Saúde |
| llm | NINTENDO ESHOP | Lazer | Compras |
| llm | CASAS BAHIA | Compras | Mercado |
| llm | Estorno - NETSHOES | Compras | Outros |
| llm | NATURA COSMETICOS | Cuidados pessoais | Saúde |
| llm | EUDORA | Cuidados pessoais | Saúde |

## Confusões mais comuns

- Contas e serviços → Impostos e taxas: 2
- Cuidados pessoais → Saúde: 2
- Alimentação → Moradia: 1
- Transporte → Contas e serviços: 1
- Transporte → Alimentação: 1
