"""Abre planilhas em .xlsx, .xlsm, .xls (Excel antigo) e .csv como um Workbook do openpyxl.

Assim o resto do código (encontrar a tabela, ler linhas, acrescentar lançamentos) é o mesmo
para qualquer formato.
"""

import csv
import io
from pathlib import Path

from openpyxl import Workbook, load_workbook

from app.services.importer import decode

SUPPORTED = {".xlsx", ".xlsm", ".xls", ".csv"}
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSM_MEDIA = "application/vnd.ms-excel.sheet.macroEnabled.12"


class SheetFormatError(ValueError):
    pass


def extension(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def open_workbook(filename: str, content: bytes, data_only: bool = False) -> Workbook:
    ext = extension(filename)
    try:
        if ext in (".xlsx", ".xlsm"):
            # keep_vba preserva as macros de .xlsm quando o arquivo é salvo de volta.
            return load_workbook(io.BytesIO(content), data_only=data_only, keep_vba=ext == ".xlsm")
        if ext == ".xls":
            return _from_xls(content)
        if ext == ".csv":
            return _from_csv(content)
    except SheetFormatError:
        raise
    except Exception as exc:
        raise SheetFormatError(
            f"Não consegui abrir o arquivo {ext}: ele pode estar corrompido ou protegido por senha."
        ) from exc
    raise SheetFormatError("Formato não suportado: envie .xlsx, .xlsm, .xls ou .csv.")


def output_format(filename: str) -> tuple[str, str]:
    """Extensão e tipo do arquivo atualizado. .xls e .csv voltam como .xlsx."""
    if extension(filename) == ".xlsm":
        return ".xlsm", XLSM_MEDIA
    return ".xlsx", XLSX_MEDIA


def _from_xls(content: bytes) -> Workbook:
    """Excel 97-2003: só valores (o formato antigo não é regravado; a saída vira .xlsx)."""
    import xlrd

    book = xlrd.open_workbook(file_contents=content)
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet in book.sheets():
        ws = workbook.create_sheet(sheet.name[:31] or "Planilha")
        for r in range(sheet.nrows):
            for c in range(sheet.ncols):
                cell = sheet.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_EMPTY:
                    continue
                if cell.ctype == xlrd.XL_CELL_DATE:
                    value = xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
                    ws.cell(r + 1, c + 1, value).number_format = "DD/MM/YYYY"
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    ws.cell(r + 1, c + 1, bool(cell.value))
                elif cell.ctype == xlrd.XL_CELL_ERROR:
                    continue
                else:
                    ws.cell(r + 1, c + 1, cell.value)
    if not workbook.worksheets:
        raise SheetFormatError("O arquivo .xls não tem abas.")
    return workbook


def _from_csv(content: bytes) -> Workbook:
    """CSV, inclusive o do Excel brasileiro (separado por ";" e com acentos em cp1252)."""
    text = decode(content)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if text[:4096].count(";") >= text[:4096].count(",") else ","
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Planilha"
    for row in csv.reader(io.StringIO(text), delimiter=delimiter):
        ws.append([value.strip() or None for value in row])
    return workbook
