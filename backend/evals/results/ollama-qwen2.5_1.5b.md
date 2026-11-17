# Avaliação da categorização: ollama · `qwen2.5:1.5b`

Conjunto `dataset.csv` · 153 transações rotuladas · tempo total 174.4s

| Métrica | Valor |
|---|---|
| Acerto de ponta a ponta | **72.5%** |
| Taxa de automação (não ficou pendente) | 100.0% |
| Regras: cobertura | 69.3% |
| Regras: acerto quando aplicadas | 100.0% |
| LLM: transações recebidas | 47 |
| LLM: acerto sobre o que as regras não resolveram | 10.6% |
| LLM: acerto com confiança ≥ 60% | 10.6% |
| LLM: acerto com confiança < 60% (0 casos) | — |

## Erros

| Etapa | Descrição | Esperado | Previsto |
|---|---|---|---|
| llm | HABIBS 345 | Alimentação | Moradia |
| llm | SPOLETO PAULISTA | Alimentação | Moradia |
| llm | EC *BOTECO DO JUCA | Alimentação | Moradia |
| llm | MP *ACAIDOTIO | Alimentação | Moradia |
| llm | COCO BAMBU MORUMBI | Alimentação | Lazer |
| llm | GIRAFFAS 210 | Alimentação | Lazer |
| llm | DIA BRASIL SOCIEDADE LTDA | Mercado | Lazer |
| llm | HIROTA FOOD EXPRESS | Mercado | Lazer |
| llm | EXTRA HIPER 123 | Mercado | Compras |
| llm | ZUL DIGITAL | Transporte | Transferências |
| llm | Pagamento de boleto - IMOBILIARIA CENTRAL | Moradia | Transferências |
| llm | TIM S A | Contas e serviços | Transferências |
| llm | LIGHT SERVICOS DE ELETRICIDADE | Contas e serviços | Transferências |
| llm | OI FIBRA | Contas e serviços | Transferências |
| llm | LAB FLEURY | Saúde | Transferências |
| llm | DR CONSULTA | Saúde | Transferências |
| llm | TOTALPASS | Saúde | Transferências |
| llm | KUMON VILA MARIANA | Educação | Outros |
| llm | ESTANTE VIRTUAL | Educação | Outros |
| llm | BOLICHE PLANET BOWLING | Lazer | Outros |
| llm | EVENTIM BRASIL | Lazer | Outros |
| llm | GOOGLE *YouTubePremium | Assinaturas | Outros |
| llm | PARAMOUNT+ | Assinaturas | Outros |
| llm | CENTAURO | Compras | Outros |
| llm | C&A MODAS | Compras | Outros |
| llm | DECATHLON | Compras | Outros |
| llm | MERCADO PAGO *LOJADOJOAO | Compras | Outros |
| llm | BUSER | Viagem | Outros |
| llm | DAS SIMPLES NACIONAL | Impostos e taxas | Outros |
| llm | Pix enviado - Maria Oliveira Souza | Transferências | Outros |
| llm | Pix enviado - Joao Pedro Santos | Transferências | Outros |
| llm | TED enviada - Carlos Lima | Transferências | Outros |
| llm | Transferência enviada - Ana Paula Ferreira | Transferências | Outros |
| llm | Transferência para conta poupança | Transferências | Outros |
| llm | Pix recebido - Cliente Projeto Freelance | Renda extra | Salário |
| llm | Pix recebido - Venda OLX | Renda extra | Outros |
| llm | TED recebida - Consultoria Silva | Renda extra | Salário |
| llm | MERCADO LIVRE VENDA | Renda extra | Mercado |
| llm | Estorno - IFD*IFOOD | Alimentação | Outros |
| llm | Estorno - AMAZON MARKETPLACE | Compras | Outros |
| llm | PAG*BarbeariaVintage | Cuidados pessoais | Outros |
| llm | MP*STUDIOSOBRANCELHAS | Cuidados pessoais | Outros |

## Confusões mais comuns

- Compras → Outros: 5
- Transferências → Outros: 5
- Alimentação → Moradia: 4
- Contas e serviços → Transferências: 3
- Saúde → Transferências: 3
