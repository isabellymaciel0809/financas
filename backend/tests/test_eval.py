"""Garante que o script de avaliação roda e que as regras não regridem."""

from app.config import Settings
from evals.run_eval import EVAL_DIR, load_cases, report, run, summarize


def test_avaliacao_baseline_de_regras():
    cases = load_cases(EVAL_DIR / "dataset.csv")
    predictions, meta = run(cases, Settings(llm_provider="none"))
    summary = summarize(predictions)

    assert summary["total"] == len(cases) >= 140
    # Quando uma regra se aplica, ela precisa estar certa: erro de regra é bug.
    assert summary["rules"]["accuracy"] == 1.0
    assert summary["rules"]["coverage"] >= 0.65
    assert "Acerto de ponta a ponta" in report(summary, predictions, meta)
