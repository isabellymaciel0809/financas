"""Apaga os dados de simulação e a importação anterior, e reimporta a planilha da empresa.

O que APAGA: transações de extrato (dados de exemplo), lotes de importação de extrato, memória
de categorias, lançamentos e fornecedores. O que MANTÉM: categorias e funcionários.
Antes de apagar, faz um backup do banco em backend/data/backups/.

Uso (dentro de backend/):
    .venv\\Scripts\\python scripts\\limpar_e_reimportar.py "..\\planilha.xlsx"

Opções:
    --banco CAMINHO   banco SQLite (padrão: financas.db)
    --sim             não pergunta confirmação
"""

import argparse
import datetime
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
TABLES_TO_CLEAR = [
    "expense_items",
    "expenses",
    "suppliers",
    "transactions",
    "import_batches",
    "merchant_memory",
]


def backup(db_path: Path) -> Path:
    folder = BACKEND / "data" / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{db_path.stem}-antes-da-limpeza-{datetime.datetime.now():%Y%m%d-%H%M%S}.db"
    source = sqlite3.connect(db_path)
    copy = sqlite3.connect(target)
    source.backup(copy)
    copy.close()
    source.close()
    return target


def clear(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    with connection:
        for table in TABLES_TO_CLEAR:
            print(f"  apagado {table}: {connection.execute(f'DELETE FROM {table}').rowcount}")
    connection.close()


def check_against_sheet(content: bytes, filename: str) -> None:
    """Compara Receita/Custo/Despesa por mês com a aba "Série Mensal Caixa" da planilha."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Expense
    from app.services.fiscal.sheet_formats import open_workbook

    workbook = open_workbook(filename, content, data_only=True)
    if "Série Mensal Caixa" not in workbook.sheetnames:
        print("\n(a planilha não tem a aba 'Série Mensal Caixa'; conferência pulada)")
        return
    sheet = {
        int(row[0]): row[1:4]
        for row in workbook["Série Mensal Caixa"].iter_rows(min_row=3, values_only=True)
        if isinstance(row[0], int | float)
    }
    system: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    with SessionLocal() as db:
        for expense in db.scalars(select(Expense).where(Expense.import_key.is_not(None))):
            system[expense.issue_date.month][expense.entry_type] += expense.total_cents / 100

    print("\nConferência com a aba 'Série Mensal Caixa' (planilha x sistema):")
    differences = 0
    for month in sorted(sheet):
        cells = []
        for value, entry_type in zip(sheet[month], ("Receita", "Custo", "Despesa"), strict=True):
            mine = system[month][entry_type]
            ok = abs((value or 0) - mine) < 0.02
            differences += not ok
            status = "ok" if ok else "DIFERENTE"
            cells.append(f"{entry_type} {(value or 0):>11,.2f} x {mine:>11,.2f} {status}")
        print(f"  mês {month:>2}: " + " | ".join(cells))
    print("\nTudo confere." if differences == 0 else f"\n{differences} valor(es) diferente(s).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("planilha", type=Path)
    parser.add_argument("--banco", type=Path, default=BACKEND / "financas.db")
    parser.add_argument("--sim", action="store_true")
    args = parser.parse_args()

    db_path = args.banco.resolve()
    if not db_path.exists():
        sys.exit(f"Banco não encontrado: {db_path}")
    if not args.planilha.exists():
        sys.exit(f"Planilha não encontrada: {args.planilha}")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    print(f"Banco: {db_path}\nPlanilha: {args.planilha}")
    print("Vai APAGAR: " + ", ".join(TABLES_TO_CLEAR) + " (mantém categorias e funcionários).")
    if not args.sim and input("Digite SIM para continuar: ").strip().upper() != "SIM":
        sys.exit("Cancelado. Nada foi alterado.")

    print(f"\nBackup salvo em: {backup(db_path)}")

    sys.path.insert(0, str(BACKEND))
    from app.database import SessionLocal, engine
    from app.migrate import run_migrations
    from app.services.fiscal.company_sheet import import_sheet

    # O banco pode estar numa versão antiga (ex.: restaurado de um backup): o código de importação
    # usa o esquema atual, então as migrações vêm antes de tudo, como quando o app inicia.
    run_migrations(engine)
    clear(db_path)

    content = args.planilha.read_bytes()
    with SessionLocal() as db:
        report = import_sheet(db, content, args.planilha.name)
    print(
        f"\nImportado da aba '{report.sheet}': {report.imported} lançamentos "
        f"({report.needs_review} para revisão por estarem incompletos na planilha), "
        f"{report.skipped} linha(s) ignorada(s) {report.skip_reasons or ''}"
    )
    for warning in report.warnings:
        print(f"  ATENÇÃO: {warning}")
    check_against_sheet(content, args.planilha.name)


if __name__ == "__main__":
    main()
