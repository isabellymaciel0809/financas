"""Assistente financeiro: a LLM responde perguntas consultando o banco por meio de ferramentas.

A LLM nunca faz contas nem inventa valores: ela escolhe uma ferramenta, o backend executa a
consulta em SQL e devolve os números prontos. Os argumentos são validados com Pydantic; um
argumento inválido volta para a LLM como erro, para ela corrigir e tentar de novo.
"""

from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, Transaction
from app.services.categorizer.llm import ChatResult, LLMProvider, ToolSpec
from app.services.text import simplify

UNCATEGORIZED = "Sem categoria"


class PeriodArgs(BaseModel):
    data_inicio: date
    data_fim: date


class SearchArgs(BaseModel):
    data_inicio: date | None = None
    data_fim: date | None = None
    categoria: str | None = None
    texto: str | None = Field(None, max_length=100)
    tipo: Literal["despesa", "receita"] | None = None
    ordem: Literal["maiores", "recentes"] = "recentes"
    limite: int = Field(10, ge=1, le=50)


class MonthlyArgs(BaseModel):
    meses: int = Field(6, ge=1, le=24)


TOOLS = [
    ToolSpec(
        name="resumo_financeiro",
        description=(
            "Totais de um período: receitas, despesas, saldo e quanto foi gasto/recebido em cada "
            "categoria. Use para perguntas como 'quanto gastei em outubro?' ou 'quanto gastei com "
            "alimentação este mês?'. As datas são inclusivas."
        ),
        parameters={
            "type": "object",
            "properties": {
                "data_inicio": {"type": "string", "format": "date", "description": "AAAA-MM-DD"},
                "data_fim": {"type": "string", "format": "date", "description": "AAAA-MM-DD"},
            },
            "required": ["data_inicio", "data_fim"],
        },
    ),
    ToolSpec(
        name="buscar_transacoes",
        description=(
            "Lista transações com filtros opcionais e devolve também a quantidade e a soma de "
            "todas que casam com o filtro. Use para 'maiores gastos', 'quanto gastei no iFood', "
            "'quais compras fiz na Amazon'. Valores negativos são despesas."
        ),
        parameters={
            "type": "object",
            "properties": {
                "data_inicio": {"type": "string", "format": "date"},
                "data_fim": {"type": "string", "format": "date"},
                "categoria": {"type": "string", "description": "Nome exato de uma categoria"},
                "texto": {"type": "string", "description": "Trecho da descrição, ex.: 'ifood'"},
                "tipo": {"type": "string", "enum": ["despesa", "receita"]},
                "ordem": {"type": "string", "enum": ["maiores", "recentes"]},
                "limite": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
    ),
    ToolSpec(
        name="evolucao_mensal",
        description="Receitas e despesas mês a mês, terminando no mês mais recente com dados.",
        parameters={
            "type": "object",
            "properties": {"meses": {"type": "integer", "minimum": 1, "maximum": 24}},
        },
    ),
]

SYSTEM_TEMPLATE = """Você é o assistente de um app de finanças pessoais e responde em português \
do Brasil, de forma curta e direta.

Hoje é {today}. Categorias existentes: {categories}.

Regras:
- Todo número da sua resposta precisa vir de uma ferramenta. Nunca estime nem invente valores.
- Escolha as datas a partir de hoje: "este mês" vai do dia 1 do mês atual até hoje; "mês \
passado" é o mês anterior inteiro.
- Para filtrar por categoria, use exatamente um dos nomes da lista acima.
- Formate dinheiro como R$ 1.234,56.
- Se não houver dados para a pergunta, diga isso claramente.
- Se a pergunta não for sobre as finanças do usuário, explique educadamente que você só \
responde sobre os dados do app."""


def _reais(cents: int) -> float:
    return round(cents / 100, 2)


class Toolbox:
    """Executa as ferramentas do assistente sobre o banco."""

    def __init__(self, db: Session, today: date | None = None):
        self.db = db
        self.today = today or date.today()
        self.categories = list(db.scalars(select(Category).order_by(Category.name)))

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "resumo_financeiro": (PeriodArgs, self.resumo_financeiro),
            "buscar_transacoes": (SearchArgs, self.buscar_transacoes),
            "evolucao_mensal": (MonthlyArgs, self.evolucao_mensal),
        }
        if name not in handlers:
            return {"erro": f"Ferramenta desconhecida: {name}"}
        schema, handler = handlers[name]
        # Modelos pequenos às vezes mandam campos vazios ou "null" em vez de omitir.
        cleaned = {k: v for k, v in arguments.items() if v not in (None, "", "null")}
        try:
            args = schema.model_validate(cleaned)
        except ValidationError as exc:
            return {"erro": f"Argumentos inválidos: {exc.errors(include_url=False)}"}
        try:
            return handler(args)
        except ValueError as exc:
            return {"erro": str(exc)}

    def _resolve_category(self, name: str) -> Category:
        wanted = simplify(name)
        for category in self.categories:
            if simplify(category.name) == wanted:
                return category
        valid = ", ".join(c.name for c in self.categories)
        raise ValueError(f"Categoria '{name}' não existe. Use uma destas: {valid}")

    def resumo_financeiro(self, args: PeriodArgs) -> dict[str, Any]:
        if args.data_fim < args.data_inicio:
            raise ValueError("data_fim é anterior a data_inicio.")
        rows = self.db.execute(
            select(Transaction.amount_cents, Category.name)
            .outerjoin(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.date >= args.data_inicio,
                Transaction.date < args.data_fim + timedelta(days=1),
            )
        ).all()
        expenses: dict[str, list[int]] = {}
        incomes: dict[str, list[int]] = {}
        for amount, category in rows:
            bucket = incomes if amount > 0 else expenses
            bucket.setdefault(category or UNCATEGORIZED, []).append(abs(amount))

        def ranked(groups: dict[str, list[int]]) -> list[dict[str, Any]]:
            items = sorted(groups.items(), key=lambda kv: sum(kv[1]), reverse=True)
            return [
                {"categoria": k, "total": _reais(sum(v)), "quantidade": len(v)} for k, v in items
            ]

        income = sum(a for a, _ in rows if a > 0)
        expense = -sum(a for a, _ in rows if a < 0)
        return {
            "periodo": f"{args.data_inicio} a {args.data_fim}",
            "quantidade_transacoes": len(rows),
            "receitas": _reais(income),
            "despesas": _reais(expense),
            "saldo": _reais(income - expense),
            "despesas_por_categoria": ranked(expenses),
            "receitas_por_categoria": ranked(incomes),
        }

    def buscar_transacoes(self, args: SearchArgs) -> dict[str, Any]:
        conditions = []
        if args.data_inicio:
            conditions.append(Transaction.date >= args.data_inicio)
        if args.data_fim:
            conditions.append(Transaction.date < args.data_fim + timedelta(days=1))
        if args.categoria:
            conditions.append(Transaction.category_id == self._resolve_category(args.categoria).id)
        if args.texto:
            conditions.append(Transaction.description.ilike(f"%{args.texto}%"))
        if args.tipo == "despesa":
            conditions.append(Transaction.amount_cents < 0)
        elif args.tipo == "receita":
            conditions.append(Transaction.amount_cents > 0)

        count, total = self.db.execute(
            select(func.count(), func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                *conditions
            )
        ).one()
        order = (
            (func.abs(Transaction.amount_cents).desc(),)
            if args.ordem == "maiores"
            else (Transaction.date.desc(), Transaction.id.desc())
        )
        transactions = self.db.scalars(
            select(Transaction).where(*conditions).order_by(*order).limit(args.limite)
        ).all()
        return {
            "quantidade_encontrada": count,
            "soma": _reais(total),
            "mostrando": len(transactions),
            "transacoes": [
                {
                    "data": tx.date.isoformat(),
                    "descricao": tx.description,
                    "valor": _reais(tx.amount_cents),
                    "categoria": tx.category.name if tx.category else UNCATEGORIZED,
                }
                for tx in transactions
            ],
        }

    def evolucao_mensal(self, args: MonthlyArgs) -> dict[str, Any]:
        latest = self.db.scalar(select(func.max(Transaction.date))) or self.today
        months: list[tuple[int, int]] = []
        year, month = latest.year, latest.month
        for _ in range(args.meses):
            months.append((year, month))
            year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        months.reverse()

        start = date(*months[0], 1)
        rows = self.db.execute(
            select(Transaction.date, Transaction.amount_cents).where(Transaction.date >= start)
        ).all()
        totals = {m: [0, 0] for m in months}
        for tx_date, amount in rows:
            key = (tx_date.year, tx_date.month)
            if key in totals:
                totals[key][0 if amount > 0 else 1] += abs(amount)
        return {
            "meses": [
                {
                    "mes": f"{y:04d}-{m:02d}",
                    "receitas": _reais(inc),
                    "despesas": _reais(exp),
                    "saldo": _reais(inc - exp),
                }
                for (y, m), (inc, exp) in totals.items()
            ]
        }


def ask(
    db: Session,
    provider: LLMProvider,
    messages: list[dict[str, str]],
    today: date | None = None,
) -> ChatResult:
    toolbox = Toolbox(db, today)
    system = SYSTEM_TEMPLATE.format(
        today=toolbox.today.isoformat(),
        categories=", ".join(c.name for c in toolbox.categories),
    )
    return provider.chat_with_tools(system, messages, TOOLS, toolbox.execute)
