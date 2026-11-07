"""Normalização de descrições de extrato bancário."""

import re
import unicodedata

# Palavras que aparecem em quase todo extrato e não identificam o estabelecimento.
NOISE_WORDS = {
    "compra",
    "compras",
    "cartao",
    "debito",
    "credito",
    "pix",
    "ted",
    "doc",
    "enviado",
    "enviada",
    "recebido",
    "recebida",
    "transferencia",
    "pagamento",
    "pagto",
    "pag",
    "pgto",
    "boleto",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "para",
    "no",
    "na",
    "em",
    "com",
    "e",
    "a",
    "o",
    "ltda",
    "sa",
    "me",
    "epp",
    "eireli",
    "br",
    "bra",
    "brasil",
    "parcela",
    "parc",
    "via",
    "nupay",
    "app",
    "online",
    "int",
    "internacional",
    # Prefixos de maquininhas/intermediadores de pagamento.
    "sumup",
    "pagseguro",
    "stone",
    "cielo",
    "getnet",
    "mp",
    "mercadopago",
    "ec",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_NON_ALPHA = re.compile(r"[^a-z]+")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def simplify(text: str) -> str:
    """Minúsculas, sem acentos, só letras/números separados por espaço único."""
    return _NON_ALNUM.sub(" ", strip_accents(text).lower()).strip()


def merchant_key(description: str, max_tokens: int = 3) -> str:
    """Chave estável do estabelecimento, usada pela memória de categorias.

    "COMPRA CARTAO IFD*IFOOD 12/10 SAO PAULO" -> "ifd ifood sao"
    "Pix enviado - Padaria Pão Quente Ltda"   -> "padaria pao quente"
    """
    tokens = [t for t in _NON_ALPHA.sub(" ", strip_accents(description).lower()).split() if t]
    meaningful = [t for t in tokens if t not in NOISE_WORDS and len(t) > 1]
    chosen = meaningful or tokens
    return " ".join(chosen[:max_tokens]) or "desconhecido"


def contains_phrase(haystack_simplified: str, phrase: str) -> bool:
    """Procura `phrase` como palavras inteiras dentro de um texto já simplificado."""
    return f" {simplify(phrase)} " in f" {haystack_simplified} "
