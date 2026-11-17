# Avaliação da categorização: ollama · `qwen2.5:1.5b`

Conjunto `teste.csv` · 67 transações rotuladas · tempo total 122.28s

| Métrica | Valor |
|---|---|
| Acerto de ponta a ponta | **65.7%** |
| Taxa de automação (não ficou pendente) | 98.5% |
| Regras: cobertura | 49.3% |
| Regras: acerto quando aplicadas | 100.0% |
| LLM: transações recebidas | 34 |
| LLM: acerto sobre o que as regras não resolveram | 32.4% |
| LLM: acerto com confiança ≥ 60% | 47.8% |
| LLM: acerto com confiança < 60% (10 casos) | 0.0% |

## Erros

| Etapa | Descrição | Esperado | Previsto |
|---|---|---|---|
| llm | PAG*CAFEDAESQUINA | Alimentação | Outros |
| llm | MADERO CONTAINER | Alimentação | Outros |
| llm | EC *SORVETERIA GELATO | Alimentação | Outros |
| llm | MERCADINHO DONA ROSA | Mercado | Outros |
| llm | ZONA AZUL DIGITAL | Transporte | Outros |
| llm | OFICINA MECANICA DO TONINHO | Transporte | Outros |
| llm | INDRIVER *VIAGEM | Transporte | Outros |
| llm | LEROY MERLIN | Moradia | Outros |
| llm | SANEPAR | Contas e serviços | Outros |
| llm | ULTRAGAZ | Contas e serviços | Outros |
| llm | ODONTOPREV | Saúde | Cuidados pessoais |
| llm | DESCOMPLICA | Educação | Outros |
| llm | NINTENDO ESHOP | Lazer | Compras |
| llm | MAX STREAMING | Assinaturas | Compras |
| llm | CRUNCHYROLL | Assinaturas | Compras |
| llm | MICROSOFT 365 | Assinaturas | Compras |
| llm | APPLE MUSIC | Assinaturas | Outros |
| llm | CLICKBUS | Viagem | Transferências |
| llm | SAQUE 24H BANCO DO BRASIL | Outros | Transferências |
| llm | Pix recebido - Aula particular de violão | Renda extra | Salário |
| llm | Estorno - NETSHOES | Compras | Outros |
| llm | PAG*ManicureDaAna | Cuidados pessoais | Outros |

## Confusões mais comuns

- Alimentação → Outros: 3
- Transporte → Outros: 3
- Assinaturas → Compras: 3
- Contas e serviços → Outros: 2
- Mercado → Outros: 1
