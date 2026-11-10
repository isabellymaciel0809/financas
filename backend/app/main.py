import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth import require_user
from app.config import get_settings
from app.database import SessionLocal, engine
from app.migrate import run_migrations
from app.routers import assistant, auth, bi, dashboard, employees, expenses, misc, transactions
from app.services.ingest import seed_categories

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Build do frontend copiado pelo Dockerfile (ausente no desenvolvimento local).
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations(engine)
    with SessionLocal() as db:
        seed_categories(db)
    yield


app = FastAPI(
    title="Organizador de Finanças Pessoais",
    description="API de finanças pessoais com categorização automática por IA.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Públicas: login e health check. Todo o resto exige usuário logado (cookie ou HTTP Basic).
app.include_router(auth.router, prefix="/api")
app.include_router(misc.public_router, prefix="/api")
for module in (misc, transactions, dashboard, assistant, expenses, employees, bi):
    app.include_router(module.router, prefix="/api", dependencies=[Depends(require_user)])


if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Rota não encontrada.")
        candidate = STATIC_DIR / path
        if path and candidate.is_file() and STATIC_DIR in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
