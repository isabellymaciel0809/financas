"""Gera um extrato fictício (formato Nubank conta) com datas relativas a hoje.

Assim a demonstração sempre mostra os últimos três meses, e passa pelo mesmo fluxo de
importação que um arquivo real.
"""

import csv
import io
import random
from datetime import date, timedelta

# (dia do mês, descrição, valor em reais) — repetidos todo mês
MONTHLY = [
    (5, "Transferência recebida - Salário ACME Tecnologia Ltda", 6500.00),
    (6, "Pagamento de boleto - Aluguel Imobiliária Lar", -1800.00),
    (8, "Débito automático - ENEL Distribuição SP", -142.37),
    (9, "Pagamento de boleto - SABESP", -68.90),
    (10, "Compra no débito - NETFLIX.COM", -44.90),
    (10, "Compra no débito - Spotify", -21.90),
    (12, "Débito automático - Vivo Fibra Internet", -119.99),
    (15, "Compra no débito - SMART FIT", -119.90),
    (20, "Rendimento CDB Nubank", 37.45),
]

# (descrição, faixa de valor) — sorteados ao longo do mês
VARIABLE = [
    ("Compra no débito - IFD*IFOOD", (28, 95)),
    ("Compra no débito - IFD*IFOOD", (28, 95)),
    ("Compra no débito - UBER *TRIP", (12, 48)),
    ("Compra no débito - UBER *TRIP", (12, 48)),
    ("Compra no débito - 99APP *99POP", (10, 35)),
    ("Compra no débito - CARREFOUR HIPER", (180, 420)),
    ("Compra no débito - PAO DE ACUCAR", (60, 190)),
    ("Compra no débito - DROGASIL", (25, 140)),
    ("Compra no débito - POSTO SHELL", (150, 260)),
    ("Compra no débito - PADARIA BELLA VISTA", (12, 40)),
    ("Compra no débito - AMAZON MARKETPLACE", (60, 350)),
    ("Compra no débito - CINEMARK", (40, 90)),
    # Sem palavra-chave conhecida: ficam para o LLM (ou para o usuário corrigir).
    ("Compra no débito - PAG*JoseDaSilvaLanches", (15, 35)),
    ("Compra no débito - SumUp *BARBEARIA DO ZE", (45, 60)),
    ("Pix enviado - Maria Oliveira Souza", (50, 300)),
    ("Compra no débito - LIVRARIA DA VILA", (45, 120)),
]

EXTRA = [
    ("Pix recebido - Cliente Projeto Freelance", 1200.00),
    ("Compra no débito - LATAM AIRLINES", -890.50),
]


def build_demo_csv(today: date | None = None, seed: int = 42) -> bytes:
    today = today or date.today()
    rng = random.Random(seed)
    rows: list[tuple[date, str, float]] = []

    first_of_month = today.replace(day=1)
    months = []
    for back in range(3):
        m = first_of_month
        for _ in range(back):
            m = (m - timedelta(days=1)).replace(day=1)
        months.append(m)

    for month_start in months:
        last_day = ((month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)).day
        for day, desc, value in MONTHLY:
            d = month_start.replace(day=min(day, last_day))
            if d <= today:
                rows.append((d, desc, value))
        for desc, (low, high) in VARIABLE:
            d = month_start.replace(day=rng.randint(1, last_day))
            if d <= today:
                rows.append((d, desc, -round(rng.uniform(low, high), 2)))

    for desc, value in EXTRA:
        d = months[1].replace(day=rng.randint(1, 28))
        rows.append((d, desc, value))

    rows.sort(key=lambda r: r[0])
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Data", "Valor", "Identificador", "Descrição"])
    for i, (d, desc, value) in enumerate(rows):
        writer.writerow([d.strftime("%d/%m/%Y"), f"{value:.2f}", f"demo-{i:04d}", desc])
    return buffer.getvalue().encode("utf-8")
