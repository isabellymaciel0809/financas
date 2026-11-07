from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_llm_provider
from app.models import Category
from app.schemas import CategoryCreate, CategoryOut, HealthOut, ImportResult
from app.services.categorizer.llm import LLMProvider
from app.services.demo import build_demo_csv
from app.services.importer import StatementParseError
from app.services.ingest import import_statement

router = APIRouter()

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.get("/health", response_model=HealthOut, tags=["sistema"])
def health(provider: LLMProvider | None = Depends(get_llm_provider)):
    return HealthOut(
        status="ok",
        llm_provider=provider.name if provider else "none",
        llm_model=provider.model if provider else None,
        llm_available=provider.is_available() if provider else False,
    )


@router.get("/categories", response_model=list[CategoryOut], tags=["categorias"])
def list_categories(db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.kind, Category.name)).all()


@router.post(
    "/categories",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
    tags=["categorias"],
)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Category).where(Category.name == payload.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma categoria com esse nome.")
    category = Category(**payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.post("/imports", response_model=ImportResult, tags=["importação"])
async def upload_statement(
    file: UploadFile = File(..., description="Extrato .csv (Nubank, Inter, genérico) ou .ofx"),
    db: Session = Depends(get_db),
    provider: LLMProvider | None = Depends(get_llm_provider),
):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Arquivo maior que 5 MB.")
    try:
        return import_statement(
            db, file.filename or "extrato", content, provider, get_settings().llm_batch_size
        )
    except StatementParseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/demo", response_model=ImportResult, tags=["importação"])
def load_demo(
    db: Session = Depends(get_db),
    provider: LLMProvider | None = Depends(get_llm_provider),
):
    """Importa um extrato fictício dos últimos 3 meses (útil para conhecer o app)."""
    return import_statement(
        db, "extrato-demo.csv", build_demo_csv(), provider, get_settings().llm_batch_size
    )
