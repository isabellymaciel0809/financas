"""Cria um usuário ou troca a senha de um existente (ex.: quem esqueceu a senha).

Uso (dentro de backend/):
    .venv\\Scripts\\python scripts\\usuario.py NOME

A senha é pedida no terminal, sem aparecer na tela. Trocar a senha encerra as sessões abertas.
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth import create_user, set_password  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.migrate import run_migrations  # noqa: E402
from app.models import User  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("nome")
    args = parser.parse_args()

    password = getpass.getpass("Nova senha: ")
    if password != getpass.getpass("Repita a senha: "):
        sys.exit("As senhas não conferem. Nada foi alterado.")

    run_migrations(engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.nome.strip().casefold()))
        try:
            if user is None:
                user = create_user(db, args.nome, password)
                action = "criado"
            else:
                set_password(db, user, password)
                action = "teve a senha trocada"
        except ValueError as exc:
            sys.exit(f"{exc} Nada foi alterado.")
        db.commit()
        print(f"Usuário '{user.username}' {action}.")


if __name__ == "__main__":
    main()
