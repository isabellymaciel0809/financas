import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Sparkles, Upload } from "lucide-react";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Notify, OnQueued, Page } from "../App";
import { api, type CategorizationStats } from "../api";
import { Button, Card } from "../components/ui";
import { formatMoney, formatMonthLong, formatMonthShort, shiftMonth } from "../format";

// Paletas validadas para daltonismo (scripts/validate_palette.js do skill dataviz).
const COLORS = { income: "#2a78d6", expense: "#eb6834", grid: "#e1e0d9", axis: "#898781" };
const SOURCE_COLORS: Record<keyof CategorizationStats, string> = {
  rule: "#2a78d6",
  llm: "#1baf7a",
  memory: "#6250d6",
  none: "#d6d3cc",
};
const SOURCE_LABELS: Record<keyof CategorizationStats, string> = {
  rule: "Regras",
  llm: "IA",
  memory: "Memória",
  none: "Pendentes",
};
const TOP_CATEGORIES = 7;

export default function Dashboard({ onNavigate, notify, onQueued }: {
  onNavigate: (p: Page) => void;
  notify: Notify;
  onQueued: OnQueued;
}) {
  const [month, setMonth] = useState<string | undefined>();
  const queryClient = useQueryClient();
  const summary = useQuery({ queryKey: ["summary", month], queryFn: () => api.summary(month) });

  const demo = useMutation({
    mutationFn: api.loadDemo,
    onSuccess: (result) => {
      queryClient.invalidateQueries();
      onQueued(result.llm_queued);
      notify(
        `${result.imported} transações de exemplo importadas.` +
          (result.llm_queued ? ` A IA está categorizando ${result.llm_queued} em segundo plano.` : ""),
      );
    },
    onError: (error) => notify(error.message, "error"),
  });

  if (summary.isPending) return <p className="text-slate-500">Carregando...</p>;
  if (summary.isError)
    return <p className="text-red-600">Não foi possível falar com a API: {summary.error.message}</p>;

  const data = summary.data;
  const current = data.month;

  if (data.transaction_count === 0 && data.monthly.every((m) => !m.income_cents && !m.expense_cents)) {
    return (
      <Card className="mx-auto max-w-xl text-center">
        <div className="py-8">
          <div className="mx-auto mb-4 grid size-14 place-items-center rounded-2xl bg-emerald-50 text-emerald-600">
            <Sparkles />
          </div>
          <h1 className="text-xl font-semibold text-slate-900">Comece importando um extrato</h1>
          <p className="mt-2 text-slate-500">
            Envie o CSV ou OFX do seu banco e a categorização acontece automaticamente: memória
            das suas correções, regras e, por último, um modelo de linguagem local.
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Button onClick={() => onNavigate("import")}>
              <Upload size={16} /> Importar extrato
            </Button>
            <Button variant="ghost" onClick={() => demo.mutate()} disabled={demo.isPending}>
              {demo.isPending ? "Carregando..." : "Usar dados de exemplo"}
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  const stats = data.categorized_by;
  const totalSources = stats.memory + stats.rule + stats.llm + stats.none;
  const automated = totalSources ? Math.round(((totalSources - stats.none) / totalSources) * 100) : 0;

  const categories = data.expenses_by_category;
  const top = categories.slice(0, TOP_CATEGORIES);
  const rest = categories.slice(TOP_CATEGORIES).reduce((sum, c) => sum + c.total_cents, 0);
  const ranked = rest ? [...top, { category_id: -1, name: "Outras", icon: "…", color: "", total_cents: rest }] : top;
  const maxCategory = Math.max(1, ...ranked.map((c) => c.total_cents));

  const monthly = data.monthly.map((m) => ({
    label: formatMonthShort(m.month),
    Receitas: m.income_cents / 100,
    Despesas: m.expense_cents / 100,
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">{formatMonthLong(current)}</h1>
        <div className="flex gap-1">
          <Button variant="ghost" aria-label="Mês anterior" onClick={() => setMonth(shiftMonth(current, -1))}>
            <ChevronLeft size={16} />
          </Button>
          <Button variant="ghost" aria-label="Próximo mês" onClick={() => setMonth(shiftMonth(current, 1))}>
            <ChevronRight size={16} />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Receitas" value={formatMoney(data.income_cents)} />
        <StatTile label="Despesas" value={formatMoney(data.expense_cents)} />
        <StatTile
          label="Saldo do mês"
          value={formatMoney(data.balance_cents)}
          tone={data.balance_cents >= 0 ? "good" : "bad"}
        />
        <StatTile
          label="Categorizado automaticamente"
          value={`${automated}%`}
          hint={`${data.transaction_count} transações no mês`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card title="Despesas por categoria" className="lg:col-span-2">
          {ranked.length === 0 ? (
            <p className="text-sm text-slate-500">Nenhuma despesa neste mês.</p>
          ) : (
            <ul className="space-y-3">
              {ranked.map((c) => (
                <li key={c.category_id ?? "none"} title={`${c.name}: ${formatMoney(c.total_cents)}`}>
                  <div className="mb-1 flex justify-between text-sm">
                    <span className="text-slate-700">
                      {c.icon} {c.name}
                    </span>
                    <span className="font-medium tabular-nums text-slate-900">{formatMoney(c.total_cents)}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100">
                    <div
                      className="h-2 rounded-full"
                      style={{ width: `${(c.total_cents / maxCategory) * 100}%`, background: COLORS.income }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Receitas e despesas por mês" className="lg:col-span-3">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthly} barGap={2} margin={{ left: 8, right: 8 }}>
                <CartesianGrid vertical={false} stroke={COLORS.grid} />
                <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "#c3c2b7" }} tick={{ fill: COLORS.axis, fontSize: 12 }} />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  width={64}
                  tick={{ fill: COLORS.axis, fontSize: 12 }}
                  tickFormatter={(v: number) => `R$ ${(v / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}k`}
                />
                <Tooltip
                  cursor={{ fill: "rgba(11,11,11,0.04)" }}
                  formatter={(value) => formatMoney(Math.round(Number(value) * 100))}
                  contentStyle={{ borderRadius: 12, border: "1px solid #e2e8f0", fontSize: 13 }}
                />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 13 }} />
                <Bar dataKey="Receitas" fill={COLORS.income} radius={[4, 4, 0, 0]} maxBarSize={28} />
                <Bar dataKey="Despesas" fill={COLORS.expense} radius={[4, 4, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card
        title="Como suas transações deste mês foram categorizadas"
        action={
          stats.none > 0 && (
            <Button variant="ghost" onClick={() => onNavigate("transactions")}>
              Revisar {stats.none} pendentes
            </Button>
          )
        }
      >
        <SourceBar stats={stats} />
        <p className="mt-3 text-sm text-slate-500">
          Etapas baratas e determinísticas vêm primeiro; o modelo de linguagem só recebe o que
          sobrou. Cada correção sua vira memória e vale para as próximas importações.
        </p>
      </Card>
    </div>
  );
}

function StatTile({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm text-slate-500">{label}</p>
      <p
        className={`mt-1 text-2xl font-semibold ${
          tone === "good" ? "text-emerald-700" : tone === "bad" ? "text-red-600" : "text-slate-900"
        }`}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

function SourceBar({ stats }: { stats: CategorizationStats }) {
  const order: (keyof CategorizationStats)[] = ["rule", "llm", "memory", "none"];
  const total = order.reduce((sum, key) => sum + stats[key], 0);
  if (!total) return <p className="text-sm text-slate-500">Nenhuma transação neste mês.</p>;
  return (
    <div>
      <div className="flex h-4 gap-0.5 overflow-hidden rounded-full">
        {order
          .filter((key) => stats[key] > 0)
          .map((key) => (
            <div
              key={key}
              title={`${SOURCE_LABELS[key]}: ${stats[key]}`}
              style={{ width: `${(stats[key] / total) * 100}%`, background: SOURCE_COLORS[key] }}
            />
          ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-600">
        {order.map((key) => (
          <li key={key} className="flex items-center gap-2">
            <span className="size-2.5 rounded-full" style={{ background: SOURCE_COLORS[key] }} />
            {SOURCE_LABELS[key]} <strong className="tabular-nums text-slate-900">{stats[key]}</strong>
            <span className="text-slate-400">({Math.round((stats[key] / total) * 100)}%)</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
