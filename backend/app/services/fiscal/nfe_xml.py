"""Leitura do XML de NF-e (modelo 55) e NFC-e (modelo 65), layout nacional 4.00.

O XML já vem estruturado, então não há IA nem OCR aqui: a leitura é exata. É o caminho
preferido sempre que o fornecedor envia o XML.
"""

from datetime import date, datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET  # protege contra XXE e "billion laughs"

from app.services.fiscal.extracted import ExtractedDocument, ExtractedItem, to_cents
from app.services.fiscal.keys import parse_access_key

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

PAYMENT_METHODS = {
    "01": "Dinheiro",
    "02": "Cheque",
    "03": "Cartão de crédito",
    "04": "Cartão de débito",
    "05": "Crédito loja",
    "10": "Vale alimentação",
    "11": "Vale refeição",
    "15": "Boleto",
    "16": "Depósito bancário",
    "17": "Pix",
    "18": "Transferência",
    "99": "Outros",
}


class NFeParseError(ValueError):
    pass


def _text(node: Element | None, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(path, NS)
    return found.text.strip() if found is not None and found.text else None


def _date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def parse_nfe_xml(content: bytes) -> ExtractedDocument:
    try:
        root = SafeET.fromstring(content)
    except Exception as exc:  # defusedxml levanta tipos variados para XML inválido/perigoso
        raise NFeParseError(f"XML inválido: {exc}") from exc

    inf = root.find(".//nfe:infNFe", NS)
    if inf is None:
        raise NFeParseError("O arquivo não é um XML de NF-e/NFC-e (infNFe não encontrado).")

    key = parse_access_key(inf.get("Id", ""))
    ide = inf.find("nfe:ide", NS)
    emit = inf.find("nfe:emit", NS)

    items = []
    for det in inf.findall("nfe:det", NS):
        prod = det.find("nfe:prod", NS)
        items.append(
            ExtractedItem(
                code=_text(prod, "nfe:cProd"),
                description=_text(prod, "nfe:xProd") or "Item sem descrição",
                ncm=_text(prod, "nfe:NCM"),
                quantity=float(_text(prod, "nfe:qCom") or 1),
                unit=_text(prod, "nfe:uCom"),
                unit_price_cents=to_cents(_text(prod, "nfe:vUnCom")),
                # Valor do item já com desconto, como entra no total da nota.
                total_cents=(to_cents(_text(prod, "nfe:vProd")) or 0)
                - (to_cents(_text(prod, "nfe:vDesc")) or 0),
            )
        )

    payment_code = _text(inf, "nfe:pag/nfe:detPag/nfe:tPag")
    products = to_cents(_text(inf, "nfe:total/nfe:ICMSTot/nfe:vProd"))
    discount = to_cents(_text(inf, "nfe:total/nfe:ICMSTot/nfe:vDesc")) or 0
    return ExtractedDocument(
        items_expected_cents=None if products is None else products - discount,
        items=items,
        access_key=key.digits if key else None,
        model=_text(ide, "nfe:mod"),
        number=_text(ide, "nfe:nNF"),
        series=_text(ide, "nfe:serie"),
        issue_date=_date(_text(ide, "nfe:dhEmi") or _text(ide, "nfe:dEmi")),
        issuer_cnpj=_text(emit, "nfe:CNPJ"),
        issuer_name=_text(emit, "nfe:xFant") or _text(emit, "nfe:xNome"),
        total_cents=to_cents(_text(inf, "nfe:total/nfe:ICMSTot/nfe:vNF")),
        declared_item_count=len(items),
        payment_method=PAYMENT_METHODS.get(payment_code or "", payment_code),
    )
