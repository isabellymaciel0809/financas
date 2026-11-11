"""Sobe a API para o teste end-to-end (Playwright) com um banco novo e temporário.

Uso (o Playwright chama sozinho): python scripts/e2e_server.py 8010

O banco e os uploads ficam numa pasta temporária, apagada ao sair. As variáveis são definidas
antes de importar o app, que lê a configuração ao ser importado: assim o teste nunca abre o
financas.db do desenvolvimento, que pode ter dados reais.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    # O Playwright encerra o servidor à força (no Windows, o `finally` não roda): apaga aqui as
    # pastas que sobraram de execuções anteriores.
    for old in Path(tempfile.gettempdir()).glob("financas-e2e-*"):
        shutil.rmtree(old, ignore_errors=True)
    workdir = Path(tempfile.mkdtemp(prefix="financas-e2e-"))
    os.environ.update(
        DATABASE_URL=f"sqlite:///{(workdir / 'e2e.db').as_posix()}",
        UPLOAD_DIR=str(workdir / "uploads"),
        LLM_PROVIDER="none",  # o teste não depende do Ollama: memória e regras bastam
        RESUME_QUEUES_ON_STARTUP="false",
    )
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)

    import uvicorn

    from app.config import get_settings

    if "financas.db" in get_settings().database_url:  # trava de segurança
        raise SystemExit("O teste end-to-end não pode usar o financas.db.")
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
