import { useQuery } from "@tanstack/react-query";
import { Download, Search, X } from "lucide-react";
import { useDeferredValue, useState } from "react";
import type { Notify } from "../App";
import { api, companyCategories, ENTRY_TYPES, isIncomeType, itemsApi, type GroupTotal, type ItemFilters } from "../api";
import { Card } from "../components/ui";
import { formatDate, formatMoney } from "../format";
import ExpenseDetail from "./ExpenseDetail";
import { ProposalOptions } from "./Expenses";

const currentMonth = () => new Date().toISOString().slice(0, 7);

export default function Items({ notify }: { notify: Notify }) {
  const [month, setMonth] = useState(currentMonth());
  const [proposal, setProposal] = useState("");
  const [entryType, setEntryType] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [search, setSearch] = useState("");
  const [onlyConfirmed, setOnlyConfirmed] = useState(false);
  const [openExpense, setOpenExpense] = useState<number | null>(null);
  const deferredSearch = useDeferredValue(search);
  const deferredProposal = useDeferredValue(proposal);

  const filters: ItemFilters = {
    month: month || undefined,
    proposal: deferredProposal.trim() || undefined,
    entry_type: entryType || undefined,
    category_id: categoryId ? Number(categoryId) : undefined,
    search: deferredSearch.trim() || undefined,
    only_confirmed: onlyConfirmed,
  };
  const report = useQuery({ queryKey: ["items", filters], queryFn: () => itemsApi.list(filters) });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories, select: companyCategories });

  if (openExpense !== null) {
    return <ExpenseDetail id={openExpense} onBack={() => setOpenExpense(null)} notify={notify} />;
  }

  const hasFilters = Boolean(proposal || entryType || categoryId || search || onlyConfirmed);
  const clear = () => {
    setProposal("");
    setEntryType("");
    setCategoryId("");
    setSearch("");
    setOnlyConfirmed(false);
  };
  const field = "rounded-xl border border-slate-200 px-3 py-2 text-sm";
  const data = report.data;

  return (
    <div className="space-y-4">
      <ProposalOptions />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Itens</h1>
          <p className="text-sm text-slate-500">Todos os itens de todas as notas, como na planilha.</p>
        </div>
        <a
          href={itemsApi.exportUrl(filters)}
          className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-slate-200 ring-inset hover:bg-slate-50"
        >
          <Download size={16} /> Exportar o que está filtrado
        </a>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} aria-label="Mês" className={field} />
          <input
            list="proposals"
            value={proposal}
            onChange={(e) => setProposal(e.target.value)}
            placeholder="Proposta"
            aria-label="Proposta"
            className={`${field} w-32`}
          />
          <select value={entryType} onChange={(e) => setEntryType(e.target.value)} aria-label="Tipo" className={field}>
            <option value="">Todos os tipos</option>
            {ENTRY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} aria-label="Categoria" className={field}>
            <option value="">Todas as categorias</option>
            {categories.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.name}
              </option>
            ))}
          </select>
          <label className="relative min-w-48 flex-1">
            <Search size={16} className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar item ou fornecedor (ex.: tubo)"
              className={`${field} w-full pl-9`}
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={onlyConfirmed} onChange={(e) => setOnlyConfirmed(e.target.checked)} />
            Só confirmados
          </label>
          {hasFilters && (
            <button onClick={clear} className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
              <X size={14} /> Limpar
            </button>
          )}
        </div>
      </Card>

      {data && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <p className="text-sm text-slate-500">Total filtrado</p>
            <p className="mt-1 text-3xl font-semibold text-slate-900">{formatMoney(data.total_cents)}</p>
            <p className="mt-1 text-xs text-slate-400">{data.count} item(ns)</p>
          </Card>
          <Totals title="Por tipo" groups={data.by_type} highlightIncome />
          <Totals title="Por categoria" groups={data.by_category.slice(0, 6)} />
        </div>
      )}

      <Card>
        {report.isPending ? (
          <p className="text-slate-500">Carregando...</p>
        ) : report.isError ? (
          <p className="text-red-600">{report.error.message}</p>
        ) : data!.items.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-500">Nenhum item com esses filtros.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs tracking-wide text-slate-500 uppercase">
                <tr className="border-b border-slate-200">
                  <th className="py-2 pr-3 font-medium">Data</th>
                  <th className="py-2 pr-3 font-medium">Cliente/Fornecedor</th>
                  <th className="py-2 pr-3 font-medium">Proposta</th>
                  <th className="py-2 pr-3 font-medium">Descrição</th>
                  <th className="py-2 pr-3 font-medium">Tipo</th>
                  <th className="py-2 pr-3 font-medium">Categoria</th>
                  <th className="py-2 pr-3 text-right font-medium">Qtd</th>
                  <th className="py-2 text-right font-medium">Valor</th>
                </tr>
              </thead>
              <tbody>
                {data!.items.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => setOpenExpense(item.expense_id)}
                    title="Abrir a nota deste item"
                    className="cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50"
                  >
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-500 tabular-nums">
                      {item.issue_date ? formatDate(item.issue_date) : "—"}
                    </td>
                    <td className="max-w-40 truncate py-2 pr-3 text-slate-700">{item.counterpart ?? "—"}</td>
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-600">{item.proposal ?? ""}</td>
                    <td className="max-w-xs py-2 pr-3">
                      <span className="block truncate text-slate-800" title={item.description}>
                        {item.description}
                      </span>
                      {item.expense_status === "needs_review" && (
                        <span className="text-xs text-amber-700">nota em revisão</span>
                      )}
                    </td>
                    <td className={`py-2 pr-3 ${isIncomeType(item.entry_type) ? "font-medium text-emerald-700" : "text-slate-600"}`}>
                      {item.entry_type}
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap text-slate-600">
                      {item.category ? `${item.category.icon} ${item.category.name}` : <span className="text-amber-700">sem categoria</span>}
                    </td>
                    <td className="py-2 pr-3 text-right whitespace-nowrap text-slate-500 tabular-nums">
                      {item.quantity.toLocaleString("pt-BR")} {item.unit ?? ""}
                    </td>
                    <td className="py-2 text-right font-medium whitespace-nowrap text-slate-900 tabular-nums">
                      {formatMoney(item.total_cents)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data!.truncated && (
              <p className="mt-3 text-xs text-amber-700">
                Mostrando os primeiros {data!.items.length} de {data!.count} itens. Os totais e a exportação consideram todos.
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

function Totals({ title, groups, highlightIncome }: { title: string; groups: GroupTotal[]; highlightIncome?: boolean }) {
  const max = Math.max(1, ...groups.map((g) => g.total_cents));
  return (
    <Card title={title}>
      {groups.length === 0 ? (
        <p className="text-sm text-slate-400">—</p>
      ) : (
        <ul className="space-y-2">
          {groups.map((g) => (
            <li key={g.name}>
              <div className="flex justify-between text-sm">
                <span className={highlightIncome && isIncomeType(g.name) ? "font-medium text-emerald-700" : "text-slate-700"}>
                  {g.name}
                </span>
                <span className="font-medium text-slate-900 tabular-nums">{formatMoney(g.total_cents)}</span>
              </div>
              <div className="mt-1 h-1.5 rounded-full bg-slate-100">
                <div className="h-1.5 rounded-full bg-[#2a78d6]" style={{ width: `${(g.total_cents / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
