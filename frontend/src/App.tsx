import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, ListOrdered, MessageCircle, Upload, Wallet } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Assistant from "./pages/Assistant";
import Dashboard from "./pages/Dashboard";
import ImportPage from "./pages/Import";
import Transactions from "./pages/Transactions";

export type Page = "dashboard" | "transactions" | "assistant" | "import";
export type Notify = (message: string, tone?: "success" | "error") => void;

const NAV: { id: Page; label: string; icon: typeof Wallet }[] = [
  { id: "dashboard", label: "Visão geral", icon: LayoutDashboard },
  { id: "transactions", label: "Transações", icon: ListOrdered },
  { id: "assistant", label: "Assistente", icon: MessageCircle },
  { id: "import", label: "Importar", icon: Upload },
];

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [toast, setToast] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  const notify: Notify = useCallback((message, tone = "success") => setToast({ message, tone }), []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 4000);
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
          <nav className="flex gap-1">
            {NAV.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setPage(id)}
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${
                  page === id ? "bg-emerald-50 text-emerald-700" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Icon size={16} />
                <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </nav>
          <span
            className="ml-auto flex items-center gap-2 text-xs text-slate-500"
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
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        {page === "dashboard" && <Dashboard onNavigate={setPage} notify={notify} />}
        {page === "transactions" && <Transactions notify={notify} />}
        {page === "assistant" && <Assistant />}
        {page === "import" && <ImportPage onNavigate={setPage} notify={notify} />}
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
