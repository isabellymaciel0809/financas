import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Search, Trash2 } from "lucide-react";
import { useDeferredValue, useState } from "react";
import type { Notify, OnQueued } from "../App";
import { api, type Category, type Transaction } from "../api";
import { Button, Card, SourceBadge } from "../components/ui";
import { formatDate, formatMoney } from "../format";

export default function Transactions({ notify, onQueued, jobRunning }: {
  notify: Notify;
  onQueued: OnQueued;
  jobRunning: boolean;
}) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [month, setMonth] = useState("");
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [needsReview, setNeedsReview] = useState(false);
  const deferredSearch = useDeferredValue(search);

  const filters = { search: deferredSearch, month, category_id: categoryId, needs_review: needsReview };
  const transactions = useQuery({ queryKey: ["transactions", filters], queryFn: () => api.transactions(filters) });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    queryClient.invalidateQueries({ queryKey: ["summary"] });
  };

  const update = useMutation({
    mutationFn: ({ id, categoryId }: { id: number; categoryId: number | null }) =>
      api.updateCategory(id, categoryId),
    onSuccess: ({ similar_updated }) => {
      refresh();
      notify(
        similar_updated
          ? `Aprendido! ${similar_updated} transação(ões) do mesmo estabelecimento também foram atualizadas.`
          : "Categoria salva. Próximas compras neste estabelecimento usarão essa escolha.",
      );
    },
    onError: (error) => notify(error.message, "error"),
  });

  const remove = useMutation({
    mutationFn: api.deleteTransaction,
    onSuccess: refresh,
    onError: (error) => notify(error.message, "error"),
  });

  const categorize = useMutation({
    mutationFn: api.categorizePending,
    onSuccess: ({ queued }) => {
      onQueued(queued);
      notify(queued ? `${queued} pendente(s) enviadas para a IA.` : "Não há transações pendentes.");
    },
    onError: (error) => notify(error.message, "error"),
  });

  const llmReady = health.data?.llm_available ?? false;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">Transações</h1>
        <Button
          onClick={() => categorize.mutate()}
          disabled={!llmReady || categorize.isPending || jobRunning}
          title={llmReady ? "Envia as transações sem categoria para a IA" : "Nenhuma LLM disponível no momento"}
        >
          <Bot size={16} />
          {jobRunning ? "IA trabalhando..." : "Categorizar pendentes com IA"}
        </Button>
      </div>

      <Card>
        <div className="mb-4 flex flex-wrap gap-3">
          <label className="relative min-w-56 flex-1">
            <Search size={16} className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar descrição..."
              className="w-full rounded-xl border border-slate-200 py-2 pr-3 pl-9 text-sm outline-none focus:border-emerald-500"
            />
          </label>
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            aria-label="Mês"
            className="rounded-xl border border-slate-200 px-3 py-2 text-sm"
          />
          <select
            value={categoryId ?? ""}
            onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : undefined)}
            aria-label="Categoria"
            className="rounded-xl border border-slate-200 px-3 py-2 text-sm"
          >
            <option value="">Todas as categorias</option>
            {categories.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.name}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={needsReview} onChange={(e) => setNeedsReview(e.target.checked)} />
            Só o que precisa de revisão
          </label>
        </div>

        {transactions.isPending ? (
          <p className="text-slate-500">Carregando...</p>
        ) : transactions.isError ? (
          <p className="text-red-600">{transactions.error.message}</p>
        ) : transactions.data.items.length === 0 ? (
          <p className="py-8 text-center text-slate-500">Nenhuma transação encontrada.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs tracking-wide text-slate-500 uppercase">
                <tr className="border-b border-slate-200">
                  <th className="py-2 pr-3 font-medium">Data</th>
                  <th className="py-2 pr-3 font-medium">Descrição</th>
                  <th className="py-2 pr-3 font-medium">Categoria</th>
                  <th className="py-2 pr-3 font-medium">Origem</th>
                  <th className="py-2 pr-3 text-right font-medium">Valor</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {transactions.data.items.map((tx) => (
                  <Row
                    key={tx.id}
                    tx={tx}
                    categories={categories.data ?? []}
                    onChange={(id) => update.mutate({ id: tx.id, categoryId: id })}
                    onDelete={() => remove.mutate(tx.id)}
                  />
                ))}
              </tbody>
            </table>
            <p className="mt-3 text-xs text-slate-400">
              {transactions.data.total} transação(ões). Ao trocar a categoria, o app aprende o
              estabelecimento e aplica a escolha nas compras semelhantes.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}

function Row({ tx, categories, onChange, onDelete }: {
  tx: Transaction;
  categories: Category[];
  onChange: (categoryId: number | null) => void;
  onDelete: () => void;
}) {
  const kind = tx.amount_cents >= 0 ? "income" : "expense";
  // Sugere primeiro as categorias do mesmo tipo (receita/despesa).
  const sorted = [...categories].sort((a, b) => Number(b.kind === kind) - Number(a.kind === kind));
  return (
    <tr className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
      <td className="py-2 pr-3 whitespace-nowrap text-slate-500 tabular-nums">{formatDate(tx.date)}</td>
      <td className="max-w-xs truncate py-2 pr-3" title={tx.description}>{tx.description}</td>
      <td className="py-2 pr-3">
        <select
          value={tx.category?.id ?? ""}
          onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
          aria-label={`Categoria de ${tx.description}`}
          className={`w-44 rounded-lg border px-2 py-1 text-sm ${
            tx.category ? "border-slate-200" : "border-amber-300 bg-amber-50"
          }`}
        >
          <option value="">— escolher —</option>
          {sorted.map((c) => (
            <option key={c.id} value={c.id}>
              {c.icon} {c.name}
            </option>
          ))}
        </select>
      </td>
      <td className="py-2 pr-3">
        <SourceBadge source={tx.categorized_by} confidence={tx.confidence} />
      </td>
      <td
        className={`py-2 pr-3 text-right font-medium whitespace-nowrap tabular-nums ${
          tx.amount_cents >= 0 ? "text-emerald-700" : "text-slate-900"
        }`}
      >
        {formatMoney(tx.amount_cents)}
      </td>
      <td className="py-2 text-right">
        <button
          onClick={onDelete}
          aria-label="Excluir"
          className="rounded-lg p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
        >
          <Trash2 size={15} />
        </button>
      </td>
    </tr>
  );
}
