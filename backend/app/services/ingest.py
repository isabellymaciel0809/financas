"""Caso de uso "importar extrato": parse -> deduplicação -> gravação -> categorização."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, ImportBatch, Transaction
from app.schemas import ImportResult
from app.services.categorizer.defaults import DEFAULT_CATEGORIES
from app.services.categorizer.llm import LLMProvider
from app.services.categorizer.pipeline import categorize_transactions
from app.services.importer import fingerprints, parse_file
from app.services.text import merchant_key


def import_statement(
    db: Session,
    filename: str,
    content: bytes,
    provider: LLMProvider | None,
    batch_size: int = 25,
) -> ImportResult:
    parsed = parse_file(filename, content)
    prints = fingerprints(parsed.rows)
    existing = set(
        db.scalars(select(Transaction.fingerprint).where(Transaction.fingerprint.in_(prints)))
    )

    batch = ImportBatch(filename=filename[:255], source_format=parsed.source_format)
    db.add(batch)
    db.flush()

    new_transactions = [
        Transaction(
            date=row.date,
            description=row.description,
            amount_cents=row.amount_cents,
            merchant_key=merchant_key(row.description),
            fingerprint=fp,
            import_batch_id=batch.id,
        )
        for row, fp in zip(parsed.rows, prints, strict=True)
        if fp not in existing
    ]
    db.add_all(new_transactions)
    db.flush()

    outcome = categorize_transactions(db, new_transactions, provider, batch_size)
    db.commit()

    return ImportResult(
        filename=filename,
        source_format=parsed.source_format,
        imported=len(new_transactions),
        duplicates=len(parsed.rows) - len(new_transactions),
        categorization=outcome.stats,
        llm_error=outcome.llm_error,
    )


def seed_categories(db: Session) -> None:
    existing = set(db.scalars(select(Category.name)))
    for name, kind, color, icon in DEFAULT_CATEGORIES:
        if name not in existing:
            db.add(Category(name=name, kind=kind, color=color, icon=icon))
    db.commit()
