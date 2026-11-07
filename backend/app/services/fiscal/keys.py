"""Validação de chave de acesso (NF-e/NFC-e) e CNPJ pelos dígitos verificadores.

São checagens determinísticas e baratas: pegam erros de OCR antes que um número errado vire
lançamento (ex.: um "3" lido como "8" quase sempre invalida o dígito verificador).
"""

import re
from dataclasses import dataclass
from datetime import date

_DIGITS = re.compile(r"\D")

MODEL_NAMES = {"55": "NF-e", "65": "NFC-e", "59": "CF-e SAT"}


def only_digits(text: str) -> str:
    return _DIGITS.sub("", text)


def _mod11(digits: str, weights: list[int]) -> int:
    total = sum(int(d) * weights[i % len(weights)] for i, d in enumerate(reversed(digits)))
    rest = total % 11
    return 0 if rest < 2 else 11 - rest


def is_valid_cnpj(cnpj: str) -> bool:
    digits = only_digits(cnpj)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    first = _mod11(digits[:12], [2, 3, 4, 5, 6, 7, 8, 9])
    second = _mod11(digits[:12] + str(first), [2, 3, 4, 5, 6, 7, 8, 9])
    return digits[12:] == f"{first}{second}"


def format_cnpj(cnpj: str) -> str:
    d = only_digits(cnpj)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else cnpj


@dataclass(frozen=True)
class AccessKey:
    """Chave de acesso de 44 dígitos: UF, AAMM, CNPJ do emitente, modelo, série, número..."""

    digits: str

    @property
    def uf(self) -> str:
        return self.digits[:2]

    @property
    def year_month(self) -> date:
        return date(2000 + int(self.digits[2:4]), int(self.digits[4:6]), 1)

    @property
    def issuer_cnpj(self) -> str:
        return self.digits[6:20]

    @property
    def model(self) -> str:
        return self.digits[20:22]

    @property
    def series(self) -> str:
        return str(int(self.digits[22:25]))

    @property
    def number(self) -> str:
        return str(int(self.digits[25:34]))


# 44 dígitos seguidos ou em grupos de 4 separados por um espaço, sem dígitos colados nas pontas.
# Cobre a URL do QR Code ("?p=3526...|2|1|...") e a chave impressa no cupom.
_KEY = re.compile(r"(?<!\d)(\d{4}(?: ?\d{4}){10})(?!\d)")


def parse_access_key(text: str) -> AccessKey | None:
    """Extrai a primeira chave de acesso válida (dígito verificador e mês conferidos)."""
    for match in _KEY.finditer(text):
        key = only_digits(match.group(1))
        if _mod11(key[:43], [2, 3, 4, 5, 6, 7, 8, 9]) == int(key[43]) and 1 <= int(key[4:6]) <= 12:
            return AccessKey(key)
    return None
