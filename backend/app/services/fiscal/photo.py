"""Leitura de foto de cupom fiscal (NFC-e): QR Code -> OCR -> leitor por padrões -> formato comum.

Etapas, da mais confiável para a menos:
1. QR Code (determinístico): dá a chave de acesso, validada pelo dígito verificador, e com
   ela o CNPJ do emitente, o número e a série da nota.
2. OCR local (RapidOCR, roda na CPU): transforma a imagem em linhas de texto.
3. Leitor por padrões (`receipt_parser.py`): transforma as linhas em itens e totais.
4. Opcional: LLM, só se o leitor não fechar a soma e houver um modelo rápido disponível.
Depois, `validation.py` confere tudo (soma dos itens, quantidade, CNPJ) antes de lançar.
"""

import logging
import threading
from datetime import date, datetime
from typing import Any

import cv2
import numpy as np

from app.services.categorizer.llm import LLMError, LLMProvider
from app.services.fiscal.extracted import ExtractedDocument, ExtractedItem, to_cents
from app.services.fiscal.keys import only_digits, parse_access_key
from app.services.fiscal.receipt_parser import parse_receipt_lines

logger = logging.getLogger(__name__)


class PhotoReadError(RuntimeError):
    pass


# --- QR Code -----------------------------------------------------------------------------


def decode_qr(image: np.ndarray) -> str | None:
    """Tenta ler o QR Code com ampliação e binarização (fotos de celular costumam precisar)."""
    import zxingcpp

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    variants = [gray]
    for scale in (2, 3):
        big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        variants += [big, cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
    for variant in variants:
        results = zxingcpp.read_barcodes(
            variant, formats=zxingcpp.BarcodeFormat.QRCode, try_rotate=True, try_downscale=True
        )
        if results:
            return results[0].text
    return None


# --- OCR -----------------------------------------------------------------------------------

_ocr_engine = None
_ocr_lock = threading.Lock()


def _engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    return _ocr_engine


def ocr_lines(image: np.ndarray) -> list[str]:
    """OCR e agrupamento das palavras em linhas, de cima para baixo.

    Duas caixas ficam na mesma linha quando se sobrepõem bastante na vertical. Isso tolera foto
    levemente torta melhor do que comparar só o centro das caixas.
    """
    with _ocr_lock:  # o motor de OCR não é thread-safe
        result, _ = _engine()(image)
    if not result:
        return []
    boxes = []
    for box, text, _score in result:
        ys = [p[1] for p in box]
        boxes.append((min(ys), max(ys), min(p[0] for p in box), text))
    boxes.sort(key=lambda b: (b[0] + b[1]) / 2)

    lines: list[dict] = []
    for top, bottom, x, text in boxes:
        line = lines[-1] if lines else None
        if line is not None:
            overlap = min(bottom, line["bottom"]) - max(top, line["top"])
            smaller = min(bottom - top, line["bottom"] - line["top"])
            if smaller > 0 and overlap / smaller >= 0.5:
                line["parts"].append((x, text))
                line["top"], line["bottom"] = min(top, line["top"]), max(bottom, line["bottom"])
                continue
        lines.append({"top": top, "bottom": bottom, "parts": [(x, text)]})
    return ["  ".join(t for _, t in sorted(line["parts"])) for line in lines]


# --- LLM -----------------------------------------------------------------------------------

EXTRACTION_SYSTEM = """Você extrai dados de cupons fiscais brasileiros (NFC-e) a partir de \
texto lido por OCR.

O OCR tem erros típicos: letras e números trocados (O/0, I/1, S/5, H/M, U/V), palavras \
grudadas e pontuação perdida. Corrija esses erros quando o sentido for óbvio.

No cupom, cada item costuma ocupar duas linhas: uma com código e descrição, outra com \
quantidade, unidade, valor unitário e valor total. O OCR pode juntar ou separar essas linhas \
de outro jeito; use os números para reconstituir cada item.

Regras:
- Liste os itens na ordem em que aparecem, um por linha do cupom, mesmo que se repitam.
- Não invente itens nem valores: se um trecho estiver ilegível, deixe o item de fora.
- Números com ponto como separador decimal (2.83, 1034.33). Valor total do item = \
quantidade × valor unitário.
- valor_total do cupom é a linha "Valor total R$" (ou "Valor a pagar").
- qtd_total_itens é a linha "Qtde total de itens".
- Datas no formato DD/MM/AAAA. Campos desconhecidos ficam como texto vazio ou 0."""

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "emitente_nome": {"type": "string"},
        "emitente_cnpj": {"type": "string"},
        "data_emissao": {"type": "string"},
        "numero_nota": {"type": "string"},
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "string"},
                    "descricao": {"type": "string"},
                    "quantidade": {"type": "number"},
                    "unidade": {"type": "string"},
                    "valor_unitario": {"type": "number"},
                    "valor_total": {"type": "number"},
                },
                "required": [
                    "codigo",
                    "descricao",
                    "quantidade",
                    "unidade",
                    "valor_unitario",
                    "valor_total",
                ],
            },
        },
        "qtd_total_itens": {"type": "integer"},
        "valor_total": {"type": "number"},
        "forma_pagamento": {"type": "string"},
    },
    "required": [
        "emitente_nome",
        "emitente_cnpj",
        "data_emissao",
        "numero_nota",
        "itens",
        "qtd_total_itens",
        "valor_total",
        "forma_pagamento",
    ],
}


def _parse_date(raw: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw.strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def _from_llm(data: dict[str, Any]) -> ExtractedDocument:
    items = []
    for raw in data.get("itens") or []:
        total = to_cents(raw.get("valor_total"))
        description = str(raw.get("descricao") or "").strip()
        if not description or total is None:
            continue
        items.append(
            ExtractedItem(
                code=str(raw.get("codigo") or "").strip() or None,
                description=description[:255],
                quantity=float(raw.get("quantidade") or 1),
                unit=str(raw.get("unidade") or "").strip()[:10] or None,
                unit_price_cents=to_cents(raw.get("valor_unitario")),
                total_cents=total,
            )
        )
    total = to_cents(data.get("valor_total")) or None
    return ExtractedDocument(
        items=items,
        issuer_name=str(data.get("emitente_nome") or "").strip() or None,
        issuer_cnpj=only_digits(str(data.get("emitente_cnpj") or "")) or None,
        issue_date=_parse_date(str(data.get("data_emissao") or "")),
        number=only_digits(str(data.get("numero_nota") or "")).lstrip("0") or None,
        total_cents=total,
        items_expected_cents=total,
        declared_item_count=int(data.get("qtd_total_itens") or 0) or None,
        payment_method=str(data.get("forma_pagamento") or "").strip() or None,
    )


def _balances(document: ExtractedDocument) -> bool:
    total = document.total_cents
    return (
        bool(document.items)
        and total is not None
        and sum(i.total_cents for i in document.items) == total
    )


def read_photo(
    content: bytes, provider: LLMProvider | None, use_llm_fallback: bool = False
) -> ExtractedDocument:
    """Lê a foto. A extração por LLM é opcional: só compensa com um modelo rápido (Claude);
    com um modelo local de 3B na CPU ela passa de 30 minutos e pode entrar em loop."""
    image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise PhotoReadError("Não foi possível abrir a imagem.")

    notes: list[str] = []
    qr_text = decode_qr(image)
    key = parse_access_key(qr_text) if qr_text else None
    if key is None:
        notes.append(
            "QR Code ilegível: sem a chave de acesso não dá para garantir que a nota não é "
            "duplicada. Uma foto mais próxima do QR Code resolve."
        )

    lines = ocr_lines(image)
    raw_text = "\n".join(lines)
    if not lines:
        raise PhotoReadError("Nenhum texto encontrado na imagem.")
    if key is None:
        key = parse_access_key(raw_text)  # a chave impressa também serve, se legível

    # 1º leitor determinístico (milissegundos); 2º, se habilitado e o resultado não fechar, LLM.
    document = parse_receipt_lines(lines)
    if use_llm_fallback and provider is not None and not _balances(document):
        try:
            data = provider.extract_json(
                EXTRACTION_SYSTEM, f"Texto do cupom:\n{raw_text}", EXTRACTION_SCHEMA
            )
            candidate = _from_llm(data)
            if _balances(candidate):
                document = candidate
        except LLMError as exc:
            notes.append(f"Leitura por IA indisponível: {exc}")

    document.raw_text = raw_text
    document.notes = notes
    if key is not None:
        # Dados da chave são confiáveis (dígito verificador conferido): prevalecem sobre o OCR.
        document.access_key = key.digits
        document.model = key.model
        document.issuer_cnpj = key.issuer_cnpj
        document.number = key.number
        document.series = key.series
    return document
