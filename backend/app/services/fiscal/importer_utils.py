"""Conversão de células de planilha (Excel) em data e valor."""

from datetime import date, datetime, timedelta

from app.services.importer import parse_amount_cents, parse_date

EXCEL_EPOCH = date(1899, 12, 30)


def parse_cell_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float) and 20000 < value < 80000:
        return EXCEL_EPOCH + timedelta(days=int(value))  # data salva como número serial
    if isinstance(value, str) and value.strip():
        try:
            return parse_date(value.strip()[:10])
        except ValueError:
            return None
    return None


def parse_cell_amount(value) -> int | None:
    """Valor em centavos. Aceita número ou texto como "R$ 1.234,56"."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return round(value * 100)
    if isinstance(value, str) and value.strip():
        try:
            return parse_amount_cents(value)
        except ValueError:
            return None
    return None
