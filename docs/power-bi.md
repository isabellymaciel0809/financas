# Power BI: análise dos lançamentos

O sistema oferece uma fonte de dados com **todos os lançamentos, item a item**, já com as
dimensões que a análise usa. O Power BI lê pelo link e atualiza com um clique: não é preciso
exportar planilha.

| Link | Para quê |
|---|---|
| `http://localhost:8000/api/bi/lancamentos.json` | **Power BI** (recomendado: números e datas sem problema de vírgula) |
| `http://localhost:8000/api/bi/lancamentos.csv` | Excel (separador `;`, vírgula decimal) |

> O sistema precisa estar rodando (o backend na porta 8000) quando o Power BI atualizar.

## Colunas

| Coluna | Exemplo | Observação |
|---|---|---|
| `id_lancamento`, `id_item` | 12, 57 | Um lançamento (nota) tem vários itens |
| `data`, `ano`, `mes` | 2026-10-20, 2026, 10 | `mes` é o número (1 a 12), como na planilha da empresa |
| `cliente_fornecedor`, `cnpj` | Frigelar | |
| `proposta` | 003-2026 | Nº da proposta/obra |
| `descricao` | Tubo de cobre 1/2 | Descrição do item |
| `tipo` | Receita, Custo, Despesa, Estoque, Bens, Diaria, Dedução, Caixa | Igual à coluna Tipo da planilha |
| `categoria` | Materiais e manutenção | Categoria do item (IA/regras/correções) |
| `valor` | 271.98 | Sempre positivo |
| `valor_com_sinal` | -271.98 | Entrada positiva, saída negativa, "Saldo inicial/final" zero |
| `sentido` | Entrada / Saída / Neutro | |
| `status` | Confirmado / Em revisão | Filtre "Confirmado" para números oficiais |
| `origem` | XML NF-e, Foto de cupom, Manual, Planilha da empresa | |
| `funcionario`, `reembolsar` | Ana, true | Despesas pagas por funcionário |

## Conectar (uma vez)

1. Power BI Desktop → **Obter dados** → **Consulta em branco**.
2. **Editor Avançado** → apague tudo e cole:

```powerquery
let
    Fonte = Json.Document(Web.Contents("http://localhost:8000/api/bi/lancamentos.json")),
    Tabela = Table.FromRecords(Fonte),
    Tipos = Table.TransformColumnTypes(
        Tabela,
        {
            {"data", type date}, {"ano", Int64.Type}, {"mes", Int64.Type},
            {"valor", type number}, {"valor_com_sinal", type number},
            {"reembolsar", type logical}
        },
        "en-US"
    )
in
    Tipos
```

3. O sistema exige login, então o Power BI pede credenciais na primeira vez: escolha
   **Básico** e informe o **mesmo usuário e senha** que você usa para entrar no sistema. O
   Power BI guarda essas credenciais (para trocar: **Arquivo → Opções e configurações →
   Configurações da fonte de dados**). Se você trocar a senha no sistema, atualize aqui também.
4. Renomeie a consulta para **Lancamentos** → **Fechar e aplicar**.
5. Para atualizar depois: botão **Atualizar** na faixa de opções.

> **Segurança:** o login Básico envia a senha em cada atualização. Em `http://localhost` ela não
> sai do computador; se o sistema for publicado na rede ou na internet, use HTTPS.

## Medidas DAX (DRE)

Crie em **Modelagem → Nova medida**. Os nomes de tipo são os mesmos da planilha da empresa.

```dax
Receita = CALCULATE ( SUM ( Lancamentos[valor] ), Lancamentos[tipo] = "Receita" )
Deduções = CALCULATE ( SUM ( Lancamentos[valor] ), Lancamentos[tipo] IN { "Dedução", "Deduções" } )
Custo = CALCULATE ( SUM ( Lancamentos[valor] ), Lancamentos[tipo] = "Custo" )
Despesa = CALCULATE ( SUM ( Lancamentos[valor] ), Lancamentos[tipo] IN { "Despesa", "Diaria" } )

Receita Líquida = [Receita] - [Deduções]
Lucro Bruto = [Receita Líquida] - [Custo]
Lucro Líquido = [Lucro Bruto] - [Despesa]
Margem Líquida = DIVIDE ( [Lucro Líquido], [Receita] )

Resultado (caixa) = SUM ( Lancamentos[valor_com_sinal] )
```

> Ajuste os tipos de cada medida se a empresa classificar diferente (por exemplo, se "Bens" e
> "Estoque" devem entrar no custo do mês ou não).

## Painéis sugeridos

| Visual | Campos |
|---|---|
| **DRE por mês** (matriz) | Linhas: medidas Receita → Lucro Líquido; Colunas: `mes` |
| **Resultado por proposta** (barras) | Eixo: `proposta`; Valores: Receita, Custo, Lucro Bruto |
| **Custos por categoria** (barras) | Eixo: `categoria`; Valores: Custo; filtro `tipo` = Custo |
| **Maiores fornecedores** (tabela) | `cliente_fornecedor`, Custo + Despesa, ordenado |
| **Evolução do caixa** (linha) | Eixo: `data`; Valor: Resultado (caixa) acumulado |
| **Segmentações** | `ano`, `mes`, `proposta`, `status`, `origem` |

Dica: deixe uma segmentação de `status` em "Confirmado" para que lançamentos ainda em revisão
não entrem nos números oficiais.
