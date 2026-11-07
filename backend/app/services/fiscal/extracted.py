"""Formato intermediário comum: o que foi lido de um documento, venha de XML ou de foto."""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class ExtractedItem:
    description: str
    total_cents: int
    quantity: float = 1.0
    unit: str | None = None
    unit_price_cents: int | None = None
    code: str | None = None
    ncm: str | None = None


@dataclass
class ExtractedDocument:
    items: list[ExtractedItem] = field(default_factory=list)
    access_key: str | None = None
    model: str | None = None
    number: str | None = None
    series: str | None = None
    issue_date: date | None = None
    issuer_cnpj: str | None = None
    issuer_name: str | None = None
    total_cents: int | None = None
    # Quanto a soma dos itens deve dar. No cupom é o próprio total; na NF-e o total da nota
    # inclui frete, IPI etc., então o XML informa à parte o valor dos produtos.
    items_expected_cents: int | None = None
    declared_item_count: int | None = None
    payment_method: str | None = None
    raw_text: str | None = None
    # Avisos da própria leitura (ex.: "QR Code ilegível"), somados às validações.
    notes: list[str] = field(default_factory=list)


def to_cents(value: float | str | None) -> int | None:
    if value is None or value == "":
        return None
    return round(float(str(value).replace(",", ".")) * 100)
