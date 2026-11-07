"""Avaliação da categorização: mede cobertura e acerto de cada etapa da cascata.

Roda o mesmo código do app (pipeline real, banco SQLite em memória) sobre um conjunto de
transações rotuladas à mão, e gera um relatório em evals/results/.

Uso (dentro de backend/):
    python -m evals.run_eval                                   # só regras (baseline)
    python -m evals.run_eval --provider ollama --model qwen2.5:3b
    python -m evals.run_eval --provider anthropic              # pago; exige ANTHROPIC_API_KEY

A etapa de memória não entra na avaliação: ela depende do histórico de correções do usuário.
"""

import argparse
import csv
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base, make_engine
from app.models import CategorizedBy, Transaction
from app.services.categorizer.llm import build_provider
from app.services.categorizer.pipeline import categorize_transactions
from app.services.ingest import seed_categories
from app.services.text import merchant_key

EVAL_DIR = Path(__file__).resolve().parent
REVIEW_THRESHOLD = 0.6


@dataclass
class Case:
    description: str
    amount_cents: int
    expected: str


@dataclass
class Prediction:
    description: str
    amount_cents: int
    expected: str
    predicted: str | None
    stage: str  # rule | llm | none
    confidence: float | None

    @property
    def correct(self) -> bool:
        return self.predicted == self.expected


def load_cases(path: Path) -> list[Case]:
    with path.open(encoding="utf-8") as f:
        return [
            Case(row["descricao"], round(float(row["valor"]) * 100), row["categoria"])
            for row in csv.DictReader(f)
        ]


def run(cases: list[Case], settings: Settings) -> tuple[list[Prediction], dict]:
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    seed_categories(db)

    transactions = [
        Transaction(
            date=date(2026, 10, 1),
            description=c.description,
            amount_cents=c.amount_cents,
            merchant_key=merchant_key(c.description),
            fingerprint=str(i),
        )
        for i, c in enumerate(cases)
    ]
    db.add_all(transactions)
    db.flush()

    provider = build_provider(settings)
    if provider is not None and not provider.is_available():
        raise SystemExit(f"Provedor '{provider.name}' ({provider.model}) indisponível.")

    started = time.perf_counter()
    outcome = categorize_transactions(db, transactions, provider, settings.llm_batch_size)
    elapsed = time.perf_counter() - started
    if outcome.llm_error:
        raise SystemExit(f"Erro do LLM durante a avaliação: {outcome.llm_error}")

    predictions = [
        Prediction(
            description=c.description,
            amount_cents=c.amount_cents,
            expected=c.expected,
            predicted=tx.category.name if tx.category else None,
            stage=tx.categorized_by.value,
            confidence=tx.confidence,
        )
        for c, tx in zip(cases, transactions, strict=True)
    ]
    assert all(p.stage != CategorizedBy.memory.value for p in predictions)
    meta = {
        "provider": provider.name if provider else "none",
        "model": provider.model if provider else None,
        "seconds": round(elapsed, 2),
    }
    return predictions, meta


def summarize(predictions: list[Prediction]) -> dict:
    total = len(predictions)
    by_stage = {s: [p for p in predictions if p.stage == s] for s in ("rule", "llm", "none")}
    reached_llm = len(by_stage["llm"]) + len(by_stage["none"])

    def accuracy(items: list[Prediction]) -> float | None:
        return round(sum(p.correct for p in items) / len(items), 3) if items else None

    llm = by_stage["llm"]
    confident = [p for p in llm if (p.confidence or 0) >= REVIEW_THRESHOLD]
    unsure = [p for p in llm if (p.confidence or 0) < REVIEW_THRESHOLD]
    return {
        "total": total,
        "end_to_end_accuracy": accuracy(predictions),
        "automation_rate": round((total - len(by_stage["none"])) / total, 3),
        "rules": {
            "coverage": round(len(by_stage["rule"]) / total, 3),
            "accuracy": accuracy(by_stage["rule"]),
        },
        "llm": {
            "received": reached_llm,
            "answered": len(llm),
            "accuracy_answered": accuracy(llm),
            # Acerto sobre tudo que as regras não resolveram (respostas faltando contam como erro).
            "accuracy_on_leftovers": (
                round(sum(p.correct for p in llm) / reached_llm, 3) if reached_llm else None
            ),
            "accuracy_confident": accuracy(confident),
            "accuracy_unsure": accuracy(unsure),
            "unsure_count": len(unsure),
        },
    }


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def report(summary: dict, predictions: list[Prediction], meta: dict) -> str:
    rules, llm = summary["rules"], summary["llm"]
    model = f"{meta['provider']}" + (f" · `{meta['model']}`" if meta["model"] else "")
    lines = [
        f"# Avaliação da categorização: {model}",
        "",
        f"{summary['total']} transações rotuladas · tempo total {meta['seconds']}s",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Acerto de ponta a ponta | **{pct(summary['end_to_end_accuracy'])}** |",
        f"| Taxa de automação (não ficou pendente) | {pct(summary['automation_rate'])} |",
        f"| Regras: cobertura | {pct(rules['coverage'])} |",
        f"| Regras: acerto quando aplicadas | {pct(rules['accuracy'])} |",
    ]
    if meta["provider"] != "none":
        threshold = f"{REVIEW_THRESHOLD:.0%}"
        leftovers = pct(llm["accuracy_on_leftovers"])
        lines += [
            f"| LLM: transações recebidas | {llm['received']} |",
            f"| LLM: acerto sobre o que as regras não resolveram | {leftovers} |",
            f"| LLM: acerto com confiança ≥ {threshold} | {pct(llm['accuracy_confident'])} |",
            f"| LLM: acerto com confiança < {threshold} ({llm['unsure_count']} casos) | "
            f"{pct(llm['accuracy_unsure'])} |",
        ]

    errors = [p for p in predictions if not p.correct and p.stage != "none"]
    if errors:
        lines += [
            "",
            "## Erros",
            "",
            "| Etapa | Descrição | Esperado | Previsto |",
            "|---|---|---|---|",
        ]
        lines += [f"| {p.stage} | {p.description} | {p.expected} | {p.predicted} |" for p in errors]

    confusions = Counter((p.expected, p.predicted) for p in errors)
    if len(confusions) > 1:
        lines += ["", "## Confusões mais comuns", ""]
        lines += [f"- {e} → {pr}: {n}" for (e, pr), n in confusions.most_common(5)]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--provider", choices=["none", "ollama", "anthropic"], default="none")
    parser.add_argument("--model", help="Modelo do provedor (padrão: o da configuração)")
    parser.add_argument("--dataset", type=Path, default=EVAL_DIR / "dataset.csv")
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args()

    overrides: dict = {"llm_provider": args.provider, "llm_batch_size": args.batch_size}
    if args.model and args.provider == "ollama":
        overrides["ollama_model"] = args.model
    if args.model and args.provider == "anthropic":
        overrides["anthropic_model"] = args.model
    settings = Settings(**overrides)

    predictions, meta = run(load_cases(args.dataset), settings)
    summary = summarize(predictions)
    text = report(summary, predictions, meta)

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    name = meta["provider"] + (
        f"-{meta['model'].replace(':', '_').replace('/', '_')}" if meta["model"] else ""
    )
    (out_dir / f"{name}.md").write_text(text, encoding="utf-8")
    (out_dir / f"{name}.json").write_text(
        json.dumps(
            {"meta": meta, "summary": summary, "predictions": [asdict(p) for p in predictions]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(text)
    print(f"Relatório salvo em {out_dir / name}.md")


if __name__ == "__main__":
    main()
