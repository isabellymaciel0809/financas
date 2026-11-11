"""Cria um usuário ou troca a senha de um existente (ex.: quem esqueceu a senha).

Uso (dentro de backend/):
    .venv\\Scripts\\python scripts\\usuario.py NOME
    .venv\\Scripts\\python scripts\\usuario.py NOME --admin   (também dá acesso de administração)

A senha é pedida no terminal, sem aparecer na tela. Trocar a senha encerra as sessões abertas.
Se ainda não existe nenhum usuário, o criado aqui administra o sistema (como no primeiro acesso).
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth import create_user, has_users, set_password  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.migrate import run_migrations  # noqa: E402
from app.models import User  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("nome")
    parser.add_argument(
        "--admin", action="store_true", help="dar acesso de administração (cadastrar pessoas)"
    )
    args = parser.parse_args()

    password = getpass.getpass("Nova senha: ")
    if password != getpass.getpass("Repita a senha: "):
        sys.exit("As senhas não conferem. Nada foi alterado.")

    run_migrations(engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.nome.strip().casefold()))
        try:
            if user is None:
                first = not has_users(db)
                user = create_user(db, args.nome, password, is_admin=args.admin or first)
                action = "criado"
            else:
                set_password(db, user, password)
                action = "teve a senha trocada"
                if args.admin:
                    user.is_admin = True
        except ValueError as exc:
            sys.exit(f"{exc} Nada foi alterado.")
        db.commit()
        admin = " Administra o sistema." if user.is_admin else ""
        print(f"Usuário '{user.username}' {action}.{admin}")


if __name__ == "__main__":
    main()
