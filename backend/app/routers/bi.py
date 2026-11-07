"""Fonte de dados para BI (Power BI, Excel, Looker Studio...).

Uma linha por item de lançamento, já com as dimensões que a análise usa (data, ano, mês,
cliente/fornecedor, proposta, tipo, categoria). O Power BI lê o JSON por "Obter dados > Web" e
atualiza com um clique; o passo a passo e as medidas DAX estão em docs/power-bi.md.
"""

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Expense, ExpenseItem
from app.services.fiscal.entry_types import INCOME_TYPES, NEUTRAL_TYPES
from app.services.fiscal.items_report import ItemFilters, query_items

router = APIRouter(prefix="/bi", tags=["BI"])

STATUS = {"confirmed": "Confirmado", "needs_review": "Em revisão"}
SOURCE = {"nfe_xml": "XML NF-e", "photo": "Foto de cupom", "manual": "Manual"}


def _direction(entry_type: str) -> str:
    if entry_type in INCOME_TYPES:
        return "Entrada"
    if entry_type in NEUTRAL_TYPES:
        return "Neutro"
    return "Saída"


def _record(item: ExpenseItem, expense: Expense) -> dict[str, Any]:
    day = expense.issue_date
    value = item.total_cents / 100
    direction = _direction(expense.entry_type)
    # Valor com sinal (entrada +, saída -, neutro 0): facilita somas de saldo e resultado no BI.
    signed = {"Entrada": value, "Saída": -value}.get(direction, 0.0)
    origin = "Planilha da empresa" if expense.from_spreadsheet else SOURCE[expense.source.value]
    return {
        "id_lancamento": expense.id,
        "id_item": item.id,
        "data": day.isoformat() if day else None,
        "ano": day.year if day else None,
        "mes": day.month if day else None,
        "cliente_fornecedor": expense.supplier.name if expense.supplier else None,
        "cnpj": expense.supplier.cnpj if expense.supplier else None,
        "proposta": expense.proposal,
        "descricao": item.description,
        "tipo": expense.entry_type,
        "categoria": item.category.name if item.category else "Sem categoria",
        "valor": value,
        "valor_com_sinal": signed,
        "sentido": direction,
        "status": STATUS.get(expense.status.value, expense.status.value),
        "origem": origin,
        "funcionario": expense.employee.name if expense.employee else None,
        "reembolsar": expense.reimbursable,
    }


def _records(db: Session) -> list[dict[str, Any]]:
    # Confirmados e em revisão; a coluna "status" permite filtrar no BI.
    return [_record(item, expense) for item, expense in query_items(db, ItemFilters())]


@router.get("/lancamentos.json")
def lancamentos_json(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Recomendado para o Power BI: tipos preservados, sem problema de vírgula decimal."""
    return _records(db)


@router.get("/lancamentos.csv")
def lancamentos_csv(db: Session = Depends(get_db)) -> Response:
    """Para Excel brasileiro: separador ";", vírgula decimal e acentos preservados (UTF-8 BOM)."""
    records = _records(db)
    buffer = io.StringIO()
    if records:
        writer = csv.DictWriter(buffer, fieldnames=list(records[0]), delimiter=";")
        writer.writeheader()
        for record in records:
            row = dict(record)
            for key in ("valor", "valor_com_sinal"):
                row[key] = f"{row[key]:.2f}".replace(".", ",")
            row["reembolsar"] = "Sim" if row["reembolsar"] else "Não"
            writer.writerow(row)
    return Response(
        "﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lancamentos-bi.csv"'},
    )
