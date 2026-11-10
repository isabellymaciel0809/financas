import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LayoutDashboard,
  ListOrdered,
  Loader2,
  LogOut,
  MessageCircle,
  Receipt,
  Table,
  Upload,
  UserRound,
  Users,
  Wallet,
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api, authApi } from "./api";
import AuthGate from "./components/AuthGate";
import { useCategorizationJob } from "./useCategorizationJob";

// Cada tela é baixada só quando aberta: o gráfico (Recharts) da Visão geral, por exemplo, não
// pesa no carregamento da tela de Lançamentos.
const Account = lazy(() => import("./pages/Account"));
const Assistant = lazy(() => import("./pages/Assistant"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Employees = lazy(() => import("./pages/Employees"));
const Expenses = lazy(() => import("./pages/Expenses"));
const Items = lazy(() => import("./pages/Items"));
const ImportPage = lazy(() => import("./pages/Import"));
const Transactions = lazy(() => import("./pages/Transactions"));

export type Page =
  | "expenses"
  | "items"
  | "employees"
  | "dashboard"
  | "transactions"
  | "assistant"
  | "import"
  | "account";
export type Notify = (message: string, tone?: "success" | "error") => void;
export type OnQueued = (queued: number) => void;

// Duas áreas com dados e categorias separados: a empresa (notas, cupons, planilha, Power BI) e
// as finanças pessoais (extrato bancário, assistente).
const NAV: { area: string; pages: { id: Page; label: string; icon: typeof Wallet }[] }[] = [
  {
    area: "Empresa",
    pages: [
      { id: "expenses", label: "Lançamentos", icon: Receipt },
      { id: "items", label: "Itens", icon: Table },
      { id: "employees", label: "Funcionários", icon: Users },
    ],
  },
  {
    area: "Pessoal",
    pages: [
      { id: "dashboard", label: "Visão geral", icon: LayoutDashboard },
      { id: "transactions", label: "Extrato", icon: ListOrdered },
      { id: "assistant", label: "Assistente", icon: MessageCircle },
      { id: "import", label: "Importar extrato", icon: Upload },
    ],
  },
];

export default function App() {
  return <AuthGate>{(username) => <Shell username={username} />}</AuthGate>;
}

function Shell({ username }: { username: string }) {
  const [page, setPage] = useState<Page>("expenses");
  const [toast, setToast] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const queryClient = useQueryClient();
  const logout = async () => {
    await authApi.logout().catch(() => undefined);
    queryClient.clear(); // nada do usuário anterior fica em memória
    queryClient.setQueryData(["auth"], { setup_required: false, username: null });
  };

  const notify: Notify = useCallback((message, tone = "success") => setToast({ message, tone }), []);
  const job = useCategorizationJob(
    useCallback(
      (categorized: number, error: string | null) =>
        error
          ? notify(`A IA parou com erro: ${error}`, "error")
          : notify(`IA terminou: ${categorized} transação(ões) categorizada(s).`),
      [notify],
    ),
  );

  useEffect(() => {
    if (!toast) return;
    // Erros ficam mais tempo: costumam explicar o que fazer.
    const timer = setTimeout(() => setToast(null), toast.tone === "error" ? 10000 : 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  const llm = health.data;
  const llmLabel = !llm
    ? "verificando IA..."
    : llm.llm_provider === "none"
      ? "IA desativada (só regras)"
      : `${llm.llm_provider} · ${llm.llm_model}`;

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3">
          <div className="flex items-center gap-2 font-semibold text-slate-900">
            <span className="grid size-9 place-items-center rounded-xl bg-emerald-600 text-white">
              <Wallet size={18} />
            </span>
            Finanças IA
          </div>
          <nav className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {NAV.map(({ area, pages }) => (
              <div key={area} className="flex items-center gap-1">
                <span className="hidden pr-1 text-[11px] font-semibold tracking-wide text-slate-400 uppercase lg:inline">
                  {area}
                </span>
                {pages.map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    onClick={() => setPage(id)}
                    title={`${area}: ${label}`}
                    className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${
                      page === id ? "bg-emerald-50 text-emerald-700" : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    <Icon size={16} />
                    <span className="hidden sm:inline">{label}</span>
                  </button>
                ))}
              </div>
            ))}
          </nav>
          {job.running && (
            <span className="ml-auto flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
              <Loader2 size={12} className="animate-spin" />
              IA categorizando {job.pending} transação(ões)...
            </span>
          )}
          <span
            className={`${job.running ? "" : "ml-auto"} flex items-center gap-2 text-xs text-slate-500`}
            title={llm && !llm.llm_available && llm.llm_provider !== "none"
              ? "LLM configurada, mas inacessível. O app segue funcionando com memória e regras."
              : undefined}
          >
            <span
              className={`size-2 rounded-full ${llm?.llm_available ? "bg-emerald-500" : "bg-amber-400"}`}
            />
            {llmLabel}
            {llm && !llm.llm_available && llm.llm_provider !== "none" && " (offline)"}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage("account")}
              title="Minha conta"
              className={`flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium ${
                page === "account" ? "bg-emerald-50 text-emerald-700" : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              <UserRound size={14} /> {username}
            </button>
            <button
              onClick={logout}
              title="Sair"
              aria-label="Sair"
              className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            >
              <LogOut size={14} />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Suspense
          fallback={
            <div className="grid place-items-center py-20 text-slate-400">
              <Loader2 className="animate-spin" />
            </div>
          }
        >
        {page === "expenses" && <Expenses notify={notify} />}
        {page === "items" && <Items notify={notify} />}
        {page === "employees" && <Employees notify={notify} />}
        {page === "dashboard" && <Dashboard onNavigate={setPage} notify={notify} onQueued={job.watch} />}
        {page === "transactions" && (
          <Transactions notify={notify} onQueued={job.watch} jobRunning={job.running} />
        )}
        {page === "assistant" && <Assistant />}
        {page === "import" && <ImportPage onNavigate={setPage} notify={notify} onQueued={job.watch} />}
        {page === "account" && <Account notify={notify} />}
        </Suspense>
      </main>

      {toast && (
        <div
          role="status"
          className={`fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-xl px-4 py-3 text-sm text-white shadow-lg ${
            toast.tone === "success" ? "bg-slate-900" : "bg-red-600"
          }`}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}
