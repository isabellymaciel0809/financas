import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, MessageSquarePlus, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { Notify, OnQueued } from "../App";
import { api, type TextEntryPreview } from "../api";
import { centsToInput, formatMoney, parseMoney } from "../format";
import { Button, Card } from "./ui";

const field = "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none";

/** Lançamento por texto: o backend lê a frase e devolve uma prévia; só salva ao confirmar. */
export default function QuickEntry({ notify, onQueued, llmReady }: {
  notify: Notify;
  onQueued: OnQueued;
  llmReady: boolean;
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<TextEntryPreview | null>(null);
  // Campos editáveis da prévia (o usuário pode corrigir antes de lançar).
  const [date, setDate] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<"expense" | "income">("expense");
  const [amount, setAmount] = useState("");

  const parse = useMutation({
    mutationFn: () => api.parseTextEntry(text),
    onSuccess: (p) => {
      setPreview(p);
      setDate(p.date);
      setDescription(p.description);
      setKind(p.amount_cents > 0 ? "income" : "expense");
      setAmount(centsToInput(Math.abs(p.amount_cents)));
    },
    onError: (e) => notify(e.message, "error"),
  });

  const cents = parseMoney(amount);
  const save = useMutation({
    mutationFn: () =>
      api.createTransaction({
        date,
        description: description.trim(),
        amount_cents: kind === "income" ? Math.abs(cents ?? 0) : -Math.abs(cents ?? 0),
      }),
    onSuccess: (tx) => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["summary"] });
      if (tx.categorized_by === "none" && llmReady) onQueued(1);
      notify(
        `Lançado: ${tx.description}, ${formatMoney(Math.abs(tx.amount_cents))}` +
          (tx.category ? ` em ${tx.category.name}.` : llmReady ? ". A IA vai escolher a categoria." : "."),
      );
      setPreview(null);
      setText("");
    },
    onError: (e) => notify(e.message, "error"),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) parse.mutate();
  };
  const canSave = !!date && !!description.trim() && !!cents && cents > 0 && !save.isPending;

  return (
    <Card>
      <form onSubmit={submit} className="flex gap-2">
        <label className="relative flex-1">
          <MessageSquarePlus size={16} className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-400" />
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={200}
            aria-label="Lançamento por texto"
            placeholder='Lançar rápido: "gastei 45 no mercado ontem" ou "recebi 300 de freela"'
            className="w-full rounded-xl border border-slate-200 py-2 pr-3 pl-9 text-sm outline-none focus:border-emerald-500"
          />
        </label>
        <Button type="submit" variant="ghost" disabled={!text.trim() || parse.isPending}>
          {parse.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
          {parse.isPending ? "Lendo..." : "Ler"}
        </Button>
      </form>

      {preview && (
        <section aria-label="Prévia do lançamento" className="mt-4 rounded-xl bg-slate-50 p-4">
          <p className="mb-3 text-xs text-slate-500">
            {preview.understood_by === "ia" ? "Lido pela IA" : "Lido pelas regras"}. Confira e corrija se precisar:
          </p>
          <div className="grid gap-3 sm:grid-cols-[9rem_1fr_8rem_8rem]">
            <label className="text-xs text-slate-500">
              Data
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`mt-1 ${field}`} />
            </label>
            <label className="text-xs text-slate-500">
              Descrição
              <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={255} className={`mt-1 ${field}`} />
            </label>
            <label className="text-xs text-slate-500">
              Tipo
              <select value={kind} onChange={(e) => setKind(e.target.value as "expense" | "income")} className={`mt-1 ${field}`}>
                <option value="expense">Despesa</option>
                <option value="income">Receita</option>
              </select>
            </label>
            <label className="text-xs text-slate-500">
              Valor (R$)
              <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className={`mt-1 ${field}`} />
            </label>
          </div>
          <p className="mt-3 text-sm text-slate-600">
            Categoria:{" "}
            {preview.category ? (
              <strong>
                {preview.category.icon} {preview.category.name}
              </strong>
            ) : (
              <span className="text-slate-500">{llmReady ? "a IA escolhe depois de lançar" : "fica pendente"}</span>
            )}
            {preview.category_source && (
              <span className="text-slate-400"> ({preview.category_source === "memory" ? "pela sua correção anterior" : "pelas regras"})</span>
            )}
          </p>
          {preview.warnings.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm text-amber-800">
              {preview.warnings.map((w) => (
                <li key={w}>⚠ {w}</li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex gap-2">
            <Button onClick={() => save.mutate()} disabled={!canSave}>
              <Check size={16} /> Lançar
            </Button>
            <Button variant="ghost" onClick={() => setPreview(null)}>
              <X size={16} /> Cancelar
            </Button>
          </div>
        </section>
      )}
    </Card>
  );
}
