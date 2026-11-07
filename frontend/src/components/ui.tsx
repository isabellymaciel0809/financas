import { Bot, BookMarked, Hand, HelpCircle, ListChecks } from "lucide-react";
import type { ReactNode } from "react";
import type { CategorizedBy, CategorizationStats } from "../api";

export function Card({ title, action, children, className = "" }: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-slate-600">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export const SOURCE_META: Record<
  CategorizedBy,
  { label: string; className: string; icon: typeof Bot; description: string }
> = {
  memory: {
    label: "Memória",
    className: "bg-violet-50 text-violet-700 ring-violet-200",
    icon: BookMarked,
    description: "Aprendido com uma correção sua",
  },
  rule: {
    label: "Regra",
    className: "bg-sky-50 text-sky-700 ring-sky-200",
    icon: ListChecks,
    description: "Palavra-chave conhecida",
  },
  llm: {
    label: "IA",
    className: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    icon: Bot,
    description: "Sugerido pelo modelo de linguagem",
  },
  manual: {
    label: "Manual",
    className: "bg-slate-100 text-slate-600 ring-slate-200",
    icon: Hand,
    description: "Escolhido por você",
  },
  none: {
    label: "Pendente",
    className: "bg-amber-50 text-amber-700 ring-amber-200",
    icon: HelpCircle,
    description: "Sem categoria",
  },
};

export function SourceBadge({ source, confidence }: {
  source: CategorizedBy;
  confidence: number | null;
}) {
  const meta = SOURCE_META[source];
  const Icon = meta.icon;
  const lowConfidence = source === "llm" && confidence !== null && confidence < 0.6;
  return (
    <span
      title={meta.description}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
        lowConfidence ? SOURCE_META.none.className : meta.className
      }`}
    >
      <Icon size={12} />
      {meta.label}
      {source === "llm" && confidence !== null && ` ${Math.round(confidence * 100)}%`}
    </span>
  );
}

export function StatsPills({ stats }: { stats: CategorizationStats }) {
  const keys: (keyof CategorizationStats)[] = ["memory", "rule", "llm", "none"];
  return (
    <div className="flex flex-wrap gap-2">
      {keys.map((key) => (
        <span
          key={key}
          className={`rounded-full px-3 py-1 text-sm ring-1 ring-inset ${SOURCE_META[key].className}`}
        >
          {SOURCE_META[key].label}: <strong>{stats[key]}</strong>
        </span>
      ))}
    </div>
  );
}

export function Button({ variant = "primary", className = "", ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" }) {
  const styles =
    variant === "primary"
      ? "bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-emerald-300"
      : "bg-white text-slate-700 ring-1 ring-inset ring-slate-200 hover:bg-slate-50 disabled:text-slate-400";
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${styles} ${className}`}
      {...props}
    />
  );
}
