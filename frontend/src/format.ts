const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export const formatMoney = (cents: number) => currency.format(cents / 100);

export const formatDate = (iso: string) => {
  const [year, month, day] = iso.split("-");
  return `${day}/${month}/${year}`;
};

const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

export const formatMonthShort = (ym: string) => {
  const [year, month] = ym.split("-").map(Number);
  return `${MONTHS[month - 1]}/${String(year).slice(2)}`;
};

export const formatMonthLong = (ym: string) => {
  const [year, month] = ym.split("-").map(Number);
  const name = new Date(year, month - 1, 1).toLocaleDateString("pt-BR", { month: "long" });
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} de ${year}`;
};

export const shiftMonth = (ym: string, delta: number) => {
  const [year, month] = ym.split("-").map(Number);
  const index = year * 12 + (month - 1) + delta;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
};

/** "1.234,56", "45,9" ou "45.90" -> centavos. Devolve null se não for um valor. */
export const parseMoney = (text: string): number | null => {
  const clean = text.replace(/[R$\s]/g, "");
  if (!clean) return null;
  const normalized = clean.includes(",") ? clean.replace(/\./g, "").replace(",", ".") : clean;
  const value = Number(normalized);
  return Number.isFinite(value) ? Math.round(value * 100) : null;
};

export const centsToInput = (cents: number | null | undefined) =>
  cents === null || cents === undefined ? "" : (cents / 100).toFixed(2).replace(".", ",");
