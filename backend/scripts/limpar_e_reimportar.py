"""Apaga a importação anterior e os dados de simulação DE UM USUÁRIO e reimporta a planilha.

O que APAGA (só do usuário escolhido): transações de extrato, lotes de importação, memória de
categorias, lançamentos e fornecedores. O que MANTÉM: categorias, funcionários e tudo dos outros
usuários. Antes de apagar, faz um backup do banco em backend/data/backups/.

Uso (dentro de backend/):
    .venv\\Scripts\\python scripts\\limpar_e_reimportar.py "..\\planilha.xlsx" --usuario NOME

Opções:
    --usuario NOME    dono dos dados (obrigatório quando o banco já tem usuários)
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


def clear(db_path: Path, owner: int | None) -> None:
    """Apaga só as linhas do dono (ou as sem dono, se o banco ainda não tem usuários)."""
    where, params = ("user_id = ?", (owner,)) if owner is not None else ("user_id IS NULL", ())
    connection = sqlite3.connect(db_path)
    with connection:
        for table in TABLES_TO_CLEAR:
            deleted = connection.execute(f"DELETE FROM {table} WHERE {where}", params).rowcount
            print(f"  apagado {table}: {deleted}")
    connection.close()


def check_against_sheet(content: bytes, filename: str, owner: int | None) -> None:
    """Compara Receita/Custo/Despesa por mês com a aba "Série Mensal Caixa" da planilha."""
    from sqlalchemy import select

    from app.models import Expense
    from app.services.fiscal.sheet_formats import open_workbook
    from app.tenancy import user_session

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
    with user_session(owner) as db:
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
    parser.add_argument("--usuario", help="dono dos dados")
    args = parser.parse_args()

    db_path = args.banco.resolve()
    if not db_path.exists():
        sys.exit(f"Banco não encontrado: {db_path}")
    if not args.planilha.exists():
        sys.exit(f"Planilha não encontrada: {args.planilha}")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    print(f"Banco: {db_path}\nPlanilha: {args.planilha}\nUsuário: {args.usuario or '(nenhum)'}")
    print(
        "Vai APAGAR, só deste usuário: "
        + ", ".join(TABLES_TO_CLEAR)
        + " (mantém categorias, funcionários e os dados dos outros usuários)."
    )
    if not args.sim and input("Digite SIM para continuar: ").strip().upper() != "SIM":
        sys.exit("Cancelado. Nada foi alterado.")

    print(f"\nBackup salvo em: {backup(db_path)}")

    sys.path.insert(0, str(BACKEND))
    from sqlalchemy import select

    from app.database import SessionLocal, engine
    from app.migrate import run_migrations
    from app.models import User
    from app.services.fiscal.company_sheet import import_sheet
    from app.tenancy import user_session

    # O banco pode estar numa versão antiga (ex.: restaurado de um backup): o código de importação
    # usa o esquema atual, então as migrações vêm antes de tudo, como quando o app inicia.
    run_migrations(engine)
    with SessionLocal() as db:
        users = {u.username: u.id for u in db.scalars(select(User))}
    if users and not args.usuario:
        sys.exit(f"Informe --usuario (usuários: {', '.join(sorted(users))}). Nada foi apagado.")
    owner = None
    if args.usuario:
        owner = users.get(args.usuario.strip().casefold())
        if owner is None:
            sys.exit(f"Usuário '{args.usuario}' não existe. Nada foi apagado.")
    clear(db_path, owner)

    content = args.planilha.read_bytes()
    with user_session(owner) as db:
        report = import_sheet(db, content, args.planilha.name)
    print(
        f"\nImportado da aba '{report.sheet}': {report.imported} lançamentos "
        f"({report.needs_review} para revisão por estarem incompletos na planilha), "
        f"{report.skipped} linha(s) ignorada(s) {report.skip_reasons or ''}"
    )
    for warning in report.warnings:
        print(f"  ATENÇÃO: {warning}")
    check_against_sheet(content, args.planilha.name, owner)


if __name__ == "__main__":
    main()
