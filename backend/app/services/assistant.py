"""Assistente financeiro: a LLM responde perguntas consultando o banco por meio de ferramentas.

Princípio de projeto: a LLM só escolhe a intenção; o backend faz todo o resto.
Testes com um modelo local de 3B mostraram que ele erra contas de datas, esquece de separar
receitas de despesas e copia sinais negativos para a resposta. Por isso:
- períodos são opções fechadas ("mes_passado") e o backend calcula as datas;
- a ferramenta `gastos` só enxerga despesas e devolve valores positivos;
- todo valor volta já formatado em reais, então não sobra conta para a LLM fazer.

Os argumentos são validados com Pydantic; um argumento inválido volta para a LLM como erro,
para ela corrigir e tentar de novo.
"""

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Transaction
from app.services.categorizer.llm import ChatResult, LLMProvider, ToolSpec
from app.services.text import simplify

UNCATEGORIZED = "Sem categoria"

Period = Literal[
    "este_mes",
    "mes_passado",
    "ultimos_3_meses",
    "ultimos_6_meses",
    "este_ano",
    "ano_passado",
    "tudo",
]

PERIOD_HELP = (
    "este_mes = do dia 1 do mês atual até hoje; mes_passado = o mês anterior inteiro; "
    "ultimos_3_meses e ultimos_6_meses incluem o mês atual; este_ano = desde 1º de janeiro; "
    "tudo = todo o histórico."
)


def brl(cents: int) -> str:
    value = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if cents < 0 else ''}R$ {value}"


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def resolve_period(period: Period, month: str | None, today: date) -> tuple[date, date]:
    """Devolve (início, fim) inclusivos. `month` (AAAA-MM) tem prioridade sobre `period`."""
    if month:
        start = date(int(month[:4]), int(month[5:7]), 1)
        return start, _add_months(start, 1) - timedelta(days=1)
    first_of_month = today.replace(day=1)
    match period:
        case "este_mes":
            return first_of_month, today
        case "mes_passado":
            return _add_months(first_of_month, -1), first_of_month - timedelta(days=1)
        case "ultimos_3_meses":
            return _add_months(first_of_month, -2), today
        case "ultimos_6_meses":
            return _add_months(first_of_month, -5), today
        case "este_ano":
            return date(today.year, 1, 1), today
        case "ano_passado":
            return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        case _:
            return date(1900, 1, 1), today


class PeriodArgs(BaseModel):
    periodo: Period = "este_mes"
    mes: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")


class SpendingArgs(PeriodArgs):
    categoria: str | None = None
    estabelecimento: str | None = Field(None, max_length=60)
    limite: int = Field(5, ge=1, le=20)

    @field_validator("limite", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> Any:
        return int(value) if isinstance(value, str) and value.isdigit() else value


class MonthlyArgs(BaseModel):
    meses: int = Field(6, ge=1, le=24)


_PERIOD_PROPERTIES = {
    "periodo": {
        "type": "string",
        "enum": list(Period.__args__),
        "description": PERIOD_HELP,
    },
    "mes": {
        "type": "string",
        "description": "Mês específico no formato AAAA-MM (ex.: 2026-10). Substitui 'periodo'.",
    },
}

TOOLS = [
    ToolSpec(
        name="gastos",
        description=(
            "Quanto foi GASTO (só despesas) em um período: total, divisão por categoria e as "
            "maiores despesas. Use para 'quanto gastei', 'maiores gastos', 'gastos com X'. "
            "Para um estabelecimento ou app (Uber, iFood, Netflix), use 'estabelecimento'; "
            "para um tipo de gasto (Alimentação, Transporte), use 'categoria'."
        ),
        parameters={
            "type": "object",
            "properties": {
                **_PERIOD_PROPERTIES,
                "categoria": {"type": "string", "description": "Nome exato de uma categoria"},
                "estabelecimento": {
                    "type": "string",
                    "description": "Trecho do nome na descrição, ex.: 'uber'",
                },
                "limite": {
                    "type": "integer",
                    "description": "Quantas das maiores despesas listar (padrão 5)",
                },
            },
        },
    ),
    ToolSpec(
        name="resumo_financeiro",
        description=(
            "Receitas, despesas e saldo de um período, com as receitas por categoria. Use para "
            "'quanto recebi', 'qual meu saldo', 'sobrou dinheiro?'."
        ),
        parameters={"type": "object", "properties": _PERIOD_PROPERTIES},
    ),
    ToolSpec(
        name="evolucao_mensal",
        description="Receitas, despesas e saldo mês a mês, para comparar meses ou ver tendência.",
        parameters={
            "type": "object",
            "properties": {"meses": {"type": "integer", "description": "Quantos meses (1 a 24)"}},
        },
    ),
]

SYSTEM_TEMPLATE = """Você é o assistente de um app de finanças pessoais. Responda em português \
do Brasil, em no máximo três frases curtas ou uma lista curta.

Hoje é {today}. Categorias: {categories}.

Sempre use uma ferramenta antes de responder sobre valores, e copie os valores exatamente como \
a ferramenta devolveu: nunca calcule, estime ou invente números. Se a ferramenta não encontrar \
nada, diga isso. Se a pergunta não for sobre as finanças do usuário, diga que você só responde \
sobre os dados do app."""


class Toolbox:
    """Executa as ferramentas do assistente sobre o banco."""

    def __init__(self, db: Session, today: date | None = None):
        self.db = db
        self.today = today or date.today()
        self.categories = list(db.scalars(select(Category).order_by(Category.name)))

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "gastos": (SpendingArgs, self.gastos),
            "resumo_financeiro": (PeriodArgs, self.resumo_financeiro),
            "evolucao_mensal": (MonthlyArgs, self.evolucao_mensal),
        }
        if name not in handlers:
            return {"erro": f"Ferramenta desconhecida: {name}. Use: {', '.join(handlers)}"}
        schema, handler = handlers[name]
        # Modelos pequenos às vezes mandam campos vazios ou "null" em vez de omitir.
        cleaned = {k: v for k, v in arguments.items() if v not in (None, "", "null", "None")}
        # E às vezes põem um período no campo do mês ({"mes": "este_mes"}). Com o qwen2.5:3b, isso
        # virava erro e o modelo desistia em vez de corrigir: o backend entende sozinho.
        if cleaned.get("mes") in Period.__args__:
            cleaned.setdefault("periodo", cleaned.pop("mes"))
        try:
            args = schema.model_validate(cleaned)
        except ValidationError as exc:
            return {"erro": f"Argumentos inválidos: {exc.errors(include_url=False)}"}
        try:
            return handler(args)
        except ValueError as exc:
            return {"erro": str(exc)}

    def _period(self, args: PeriodArgs) -> tuple[date, date, str]:
        start, end = resolve_period(args.periodo, args.mes, self.today)
        label = f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"
        return start, end, label

    def _resolve_category(self, name: str) -> Category:
        wanted = simplify(name)
        for category in self.categories:
            if simplify(category.name) == wanted:
                return category
        valid = ", ".join(c.name for c in self.categories)
        raise ValueError(f"Categoria '{name}' não existe. Use uma destas: {valid}")

    def _in_period(self, start: date, end: date):
        return (Transaction.date >= start, Transaction.date < end + timedelta(days=1))

    def gastos(self, args: SpendingArgs) -> dict[str, Any]:
        start, end, label = self._period(args)
        conditions = [*self._in_period(start, end), Transaction.amount_cents < 0]
        if args.categoria:
            conditions.append(Transaction.category_id == self._resolve_category(args.categoria).id)
        if args.estabelecimento:
            conditions.append(Transaction.description.ilike(f"%{args.estabelecimento}%"))

        transactions = self.db.scalars(select(Transaction).where(*conditions)).all()
        total = -sum(tx.amount_cents for tx in transactions)
        by_category: dict[str, int] = {}
        for tx in transactions:
            name = tx.category.name if tx.category else UNCATEGORIZED
            by_category[name] = by_category.get(name, 0) - tx.amount_cents
        largest = sorted(transactions, key=lambda tx: tx.amount_cents)[: args.limite]

        filters = [f for f in (args.categoria, args.estabelecimento) if f]
        return {
            "periodo": label,
            "filtro": " / ".join(filters) or "todas as despesas",
            "total_gasto": brl(total),
            "quantidade_de_despesas": len(transactions),
            "por_categoria": [
                {"categoria": k, "total": brl(v)}
                for k, v in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
            ],
            "maiores_despesas": [
                {
                    "data": f"{tx.date:%d/%m/%Y}",
                    "descricao": tx.description,
                    "valor": brl(-tx.amount_cents),
                    "categoria": tx.category.name if tx.category else UNCATEGORIZED,
                }
                for tx in largest
            ],
        }

    def resumo_financeiro(self, args: PeriodArgs) -> dict[str, Any]:
        start, end, label = self._period(args)
        rows = self.db.execute(
            select(Transaction.amount_cents, Category.name)
            .outerjoin(Category, Transaction.category_id == Category.id)
            .where(*self._in_period(start, end))
        ).all()
        income = sum(a for a, _ in rows if a > 0)
        expense = -sum(a for a, _ in rows if a < 0)
        by_income: dict[str, int] = {}
        for amount, category in rows:
            if amount > 0:
                key = category or UNCATEGORIZED
                by_income[key] = by_income.get(key, 0) + amount
        return {
            "periodo": label,
            "receitas": brl(income),
            "despesas": brl(expense),
            "saldo": brl(income - expense),
            "situacao": "sobrou dinheiro" if income >= expense else "gastou mais do que recebeu",
            "receitas_por_categoria": [
                {"categoria": k, "total": brl(v)}
                for k, v in sorted(by_income.items(), key=lambda kv: kv[1], reverse=True)
            ],
        }

    def evolucao_mensal(self, args: MonthlyArgs) -> dict[str, Any]:
        first = _add_months(self.today.replace(day=1), -(args.meses - 1))
        rows = self.db.execute(
            select(Transaction.date, Transaction.amount_cents).where(
                *self._in_period(first, self.today)
            )
        ).all()
        totals = {_add_months(first, i): [0, 0] for i in range(args.meses)}
        for tx_date, amount in rows:
            totals[tx_date.replace(day=1)][0 if amount > 0 else 1] += abs(amount)
        return {
            "meses": [
                {
                    "mes": f"{m:%m/%Y}",
                    "receitas": brl(inc),
                    "despesas": brl(exp),
                    "saldo": brl(inc - exp),
                }
                for m, (inc, exp) in totals.items()
            ]
        }


# Aceita "R$ 1.234,56" e também "R$ 1234,56" (o modelo nem sempre usa separador de milhar).
_MONEY = re.compile(r"R\$\s*-?\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)")


def money_values(text: str) -> dict[int, str]:
    """Valores em reais citados num texto, em centavos (sem sinal) -> como apareceram."""
    found: dict[int, str] = {}
    for match in _MONEY.finditer(text):
        raw = match.group(1).replace(".", "")
        reais, _, centavos = raw.partition(",")
        found[int(reais) * 100 + int(centavos.ljust(2, "0") or 0)] = match.group(0)
    return found


@dataclass
class Answer:
    result: ChatResult
    # Valores da resposta que não aparecem em nenhum resultado de ferramenta.
    unverified_values: list[str]


def ask(
    db: Session,
    provider: LLMProvider,
    messages: list[dict[str, str]],
    today: date | None = None,
) -> Answer:
    toolbox = Toolbox(db, today)
    system = SYSTEM_TEMPLATE.format(
        today=f"{toolbox.today:%d/%m/%Y}",
        categories=", ".join(c.name for c in toolbox.categories),
    )
    tool_outputs: list[str] = []

    def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        output = toolbox.execute(name, arguments)
        tool_outputs.append(json.dumps(output, ensure_ascii=False))
        return output

    result = provider.chat_with_tools(system, messages, TOOLS, execute)

    # Checagem de fatos: todo valor citado precisa ter vindo de uma ferramenta.
    grounded = money_values(" ".join(tool_outputs))
    unverified = [
        raw for cents, raw in money_values(result.answer).items() if cents not in grounded
    ]
    return Answer(result=result, unverified_values=unverified)
