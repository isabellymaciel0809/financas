"""Avaliação do assistente: perguntas com a consulta que as responde, sobre um extrato fixo.

Para cada pergunta de evals/assistente.json, o script faz a pergunta ao assistente de verdade
(mesmo prompt e mesmas ferramentas do app) e confere quatro coisas:

    consulta   alguma ferramenta chamada pelo modelo devolve o mesmo valor que a consulta
               esperada (filtros diferentes, mas equivalentes, contam como certos)
    valor      a resposta escrita traz esse valor
    fatos      a checagem de fatos não achou nenhum valor inventado
    frases     a resposta não usa frases proibidas para a pergunta (ex.: "último mês" quando
               a pergunta é sobre 3 meses)

Os valores esperados não são escritos à mão: vêm de rodar a consulta esperada no banco. Assim,
mudar os dados de exemplo não quebra a avaliação.

Uso (dentro de backend/):
    python -m evals.run_assistant_eval --provider ollama --model qwen2.5:3b
"""

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.database import Base, make_engine
from app.services.assistant import Toolbox, ask
from app.services.categorizer.llm import LLMError, LLMProvider, build_provider
from app.services.demo import build_demo_csv
from app.services.ingest import import_statement, seed_categories

EVAL_DIR = Path(__file__).resolve().parent
TODAY = date(2026, 11, 11)  # fixo: "este mês" e "mês passado" sempre apontam para os mesmos dados
MONEY = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")


@dataclass
class Question:
    pergunta: str
    chamada: dict[str, Any] | None  # None: pergunta fora do escopo, não deve citar valores
    valor: str | None = (
        None  # caminho no resultado da ferramenta: "total_gasto", "meses.2.despesas"
    )
    proibido: list[str] = field(default_factory=list)


@dataclass
class Result:
    pergunta: str
    resposta: str
    esperado: str | None
    consultas: list[dict[str, Any]]
    consulta_ok: bool
    valor_ok: bool
    fatos_ok: bool
    frases_ok: bool
    segundos: float
    erro: str | None = None

    @property
    def ok(self) -> bool:
        return self.consulta_ok and self.valor_ok and self.fatos_ok and self.frases_ok


def load_questions(path: Path) -> list[Question]:
    return [Question(**q) for q in json.loads(path.read_text(encoding="utf-8"))]


def demo_db() -> Session:
    """Banco em memória com o extrato de exemplo, categorizado só por regras (sem LLM)."""
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    seed_categories(db)
    import_statement(db, "extrato-demo.csv", build_demo_csv(today=TODAY), provider=None)
    db.commit()
    return db


def lookup(result: dict[str, Any], path: str) -> Any:
    value: Any = result
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value.get(part)
        if value is None:
            return None
    return value


def money_in(text: str) -> set[str]:
    """Valores em reais citados no texto, sem o "R$" ("R$1.234,56" e "1.234,56 reais" batem)."""
    return set(MONEY.findall(text))


def evaluate(db: Session, provider: LLMProvider, question: Question) -> Result:
    toolbox = Toolbox(db, today=TODAY)
    expected = None
    if question.chamada is not None:
        call = question.chamada
        expected = lookup(toolbox.execute(call["ferramenta"], call["argumentos"]), question.valor)

    started = time.perf_counter()
    try:
        answer = ask(db, provider, [{"role": "user", "content": question.pergunta}], today=TODAY)
    except LLMError as exc:
        return Result(
            question.pergunta, "", expected, [], False, False, False, False, 0.0, str(exc)
        )
    seconds = round(time.perf_counter() - started, 1)

    text = answer.result.answer
    calls = [{"ferramenta": c.name, "argumentos": c.arguments} for c in answer.result.tool_calls]
    if question.chamada is None:
        consulta_ok = valor_ok = not money_in(text)  # fora do escopo: não pode citar valores
    else:
        consulta_ok = any(
            c["ferramenta"] == question.chamada["ferramenta"]
            and lookup(toolbox.execute(c["ferramenta"], c["argumentos"]), question.valor)
            == expected
            for c in calls
        )
        valor_ok = expected is not None and money_in(str(expected)) <= money_in(text)
    lowered = text.casefold()
    return Result(
        pergunta=question.pergunta,
        resposta=text,
        esperado=expected,
        consultas=calls,
        consulta_ok=consulta_ok,
        valor_ok=valor_ok,
        fatos_ok=not answer.unverified_values,
        frases_ok=not any(p.casefold() in lowered for p in question.proibido),
        segundos=seconds,
    )


def summarize(results: list[Result]) -> dict[str, Any]:
    n = len(results)

    def rate(attr: str) -> float:
        return round(sum(getattr(r, attr) for r in results) / n, 3)

    return {
        "total": n,
        "acerto": rate("ok"),
        "consulta_certa": rate("consulta_ok"),
        "valor_na_resposta": rate("valor_ok"),
        "sem_valor_inventado": rate("fatos_ok"),
        "sem_frase_proibida": rate("frases_ok"),
        "segundos_por_pergunta": round(sum(r.segundos for r in results) / n, 1),
    }


def report(summary: dict[str, Any], results: list[Result], model: str) -> str:
    def pct(v: float) -> str:
        return f"{v * 100:.0f}%"

    lines = [
        f"# Avaliação do assistente: {model}",
        "",
        f"{summary['total']} perguntas sobre o extrato de exemplo · "
        f"{summary['segundos_por_pergunta']} s por pergunta",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| **Respostas totalmente certas** | **{pct(summary['acerto'])}** |",
        f"| Consulta certa | {pct(summary['consulta_certa'])} |",
        f"| Valor certo na resposta | {pct(summary['valor_na_resposta'])} |",
        f"| Sem valor inventado (checagem de fatos) | {pct(summary['sem_valor_inventado'])} |",
        f"| Sem frase errada sobre o período | {pct(summary['sem_frase_proibida'])} |",
        "",
        "## Perguntas",
        "",
        "| | Pergunta | Esperado | Problemas |",
        "|---|---|---|---|",
    ]
    for r in results:
        problems = [
            name
            for name, ok in (
                ("consulta", r.consulta_ok),
                ("valor", r.valor_ok),
                ("valor inventado", r.fatos_ok),
                ("frase", r.frases_ok),
            )
            if not ok
        ]
        mark = "✅" if r.ok else "❌"
        lines.append(f"| {mark} | {r.pergunta} | {r.esperado or '—'} | {', '.join(problems)} |")
    failed = [r for r in results if not r.ok]
    if failed:
        lines += ["", "## Respostas com problema", ""]
        for r in failed:
            lines += [
                f"**{r.pergunta}**",
                "",
                f"- Consultas: `{json.dumps(r.consultas, ensure_ascii=False)}`",
                f"- Resposta: {r.erro or r.resposta}".replace("\n", " "),
                "",
            ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--provider", choices=["ollama", "anthropic"], default="ollama")
    parser.add_argument("--model", help="Modelo do provedor (padrão: o da configuração)")
    args = parser.parse_args()

    overrides: dict[str, Any] = {"llm_provider": args.provider}
    if args.model:
        overrides[f"{args.provider}_model"] = args.model
    provider = build_provider(Settings(**overrides))
    if provider is None or not provider.is_available():
        raise SystemExit(f"Provedor '{args.provider}' indisponível.")

    db = demo_db()
    results = [evaluate(db, provider, q) for q in load_questions(EVAL_DIR / "assistente.json")]
    summary = summarize(results)
    text = report(summary, results, f"{provider.name} · `{provider.model}`")

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    name = f"assistente-{provider.name}-{provider.model.replace(':', '_').replace('/', '_')}"
    (out_dir / f"{name}.md").write_text(text, encoding="utf-8")
    (out_dir / f"{name}.json").write_text(
        json.dumps(
            {"summary": summary, "results": [asdict(r) for r in results]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(text)
    print(f"Relatório salvo em {out_dir / name}.md")


if __name__ == "__main__":
    main()
