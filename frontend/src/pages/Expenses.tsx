import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Download, FileCode2, FileSpreadsheet, FileUp, Loader2, PenLine, Plus } from "lucide-react";
import { useRef, useState } from "react";
import type { Notify } from "../App";
import {
  api,
  companyCategories,
  ENTRY_TYPES,
  expensesApi,
  isIncomeType,
  type ExpenseSource,
  type ExpenseStatus,
  type ExpenseSummary,
} from "../api";
import CompanySheet from "../components/CompanySheet";
import { Button, Card } from "../components/ui";
import { formatDate, formatMoney, parseMoney } from "../format";
import ExpenseDetail from "./ExpenseDetail";

export const STATUS_META: Record<ExpenseStatus, { label: string; className: string }> = {
  processing: { label: "Lendo...", className: "bg-sky-50 text-sky-700 ring-sky-200" },
  needs_review: { label: "Revisar", className: "bg-amber-50 text-amber-800 ring-amber-200" },
  confirmed: { label: "Confirmado", className: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  duplicate: { label: "Duplicado", className: "bg-slate-100 text-slate-600 ring-slate-200" },
  error: { label: "Erro", className: "bg-red-50 text-red-700 ring-red-200" },
};

const SOURCE_ICON: Record<ExpenseSource, typeof Camera> = {
  photo: Camera,
  nfe_xml: FileCode2,
  manual: PenLine,
};

const FILTERS: { id: ExpenseStatus | "all"; label: string }[] = [
  { id: "all", label: "Todos" },
  { id: "needs_review", label: "Revisar" },
  { id: "confirmed", label: "Confirmados" },
  { id: "processing", label: "Na fila" },
];

/** Sugestões de propostas já usadas, para os campos com list="proposals". */
export function ProposalOptions() {
  const proposals = useQuery({ queryKey: ["proposals"], queryFn: expensesApi.proposals });
  return (
    <datalist id="proposals">
      {proposals.data?.map((p) => <option key={p} value={p} />)}
    </datalist>
  );
}

export function StatusBadge({ status }: { status: ExpenseStatus }) {
  const meta = STATUS_META[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${meta.className}`}>
      {status === "processing" && <Loader2 size={11} className="animate-spin" />}
      {meta.label}
    </span>
  );
}

export default function Expenses({ notify }: { notify: Notify }) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ExpenseStatus | "all">("all");
  const [selected, setSelected] = useState<number | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [showSheet, setShowSheet] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [exportMonth, setExportMonth] = useState("");
  const [batchProposal, setBatchProposal] = useState("");
  const [batchType, setBatchType] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const expenses = useQuery({
    queryKey: ["expenses"],
    queryFn: () => expensesApi.list(),
    // Enquanto houver documento na fila, atualiza a lista a cada 3 s.
    refetchInterval: (query) =>
      query.state.data?.some((e) => e.status === "processing") ? 3000 : false,
  });

  const upload = useMutation({
    mutationFn: (files: File[]) =>
      expensesApi.upload(files, batchProposal.trim() || undefined, batchType || undefined),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["expenses"] });
      queryClient.invalidateQueries({ queryKey: ["proposals"] });
      notify(`${created.length} arquivo(s) na fila de leitura. Você pode continuar usando o app.`);
    },
    onError: (error) => notify(error.message, "error"),
  });

  const sendFiles = (files: FileList | null) => {
    if (files && files.length) upload.mutate(Array.from(files));
  };

  if (selected !== null) {
    return <ExpenseDetail id={selected} onBack={() => setSelected(null)} notify={notify} />;
  }

  const all = expenses.data ?? [];
  const visible = filter === "all" ? all : all.filter((e) => e.status === filter);
  const count = (status: ExpenseStatus) => all.filter((e) => e.status === status).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Lançamentos</h1>
          <p className="text-sm text-slate-500">Notas e cupons viram lançamentos sozinhos; o que não fecha vai para revisão.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="month"
            value={exportMonth}
            onChange={(e) => setExportMonth(e.target.value)}
            aria-label="Mês da exportação"
            className="rounded-xl border border-slate-200 px-3 py-2 text-sm"
          />
          <a
            href={expensesApi.exportUrl(exportMonth || undefined)}
            className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-slate-200 ring-inset hover:bg-slate-50"
          >
            <Download size={16} /> Exportar Excel
          </a>
          <Button variant="ghost" onClick={() => setShowSheet((v) => !v)}>
            <FileSpreadsheet size={16} /> Planilha da empresa
          </Button>
          <Button onClick={() => setShowManual((v) => !v)}>
            <Plus size={16} /> Lançamento manual
          </Button>
        </div>
      </div>

      {showSheet && <CompanySheet notify={notify} onClose={() => setShowSheet(false)} />}

      {showManual && (
        <ManualForm
          notify={notify}
          onDone={(id) => {
            setShowManual(false);
            queryClient.invalidateQueries({ queryKey: ["expenses"] });
            if (id) setSelected(id);
          }}
        />
      )}

      <ProposalOptions />
      <div className="flex flex-wrap items-end gap-3 rounded-2xl border border-slate-200 bg-white p-4">
        <p className="w-full text-sm font-medium text-slate-700">Enviar notas e cupons</p>
        <label className="text-xs text-slate-500">
          Proposta/obra (opcional, vale para todos os arquivos)
          <input
            list="proposals"
            value={batchProposal}
            onChange={(e) => setBatchProposal(e.target.value)}
            placeholder="Ex.: P-123"
            className="mt-1 block w-48 rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
          />
        </label>
        <label className="text-xs text-slate-500">
          Tipo
          <select
            value={batchType}
            onChange={(e) => setBatchType(e.target.value)}
            className="mt-1 block w-48 rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
          >
            <option value="">Automático ({batchProposal.trim() ? "Custo" : "Despesa"})</option>
            {ENTRY_TYPES.filter((t) => !isIncomeType(t)).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          sendFiles(e.dataTransfer.files);
        }}
        onClick={() => input.current?.click()}
        className={`cursor-pointer rounded-2xl border-2 border-dashed bg-white p-6 text-center transition-colors ${
          dragging ? "border-emerald-500 bg-emerald-50" : "border-slate-200 hover:border-emerald-400"
        }`}
      >
        <FileUp className="mx-auto mb-2 text-emerald-600" />
        <p className="font-medium text-slate-800">
          {upload.isPending ? "Enviando..." : "Arraste fotos de cupons ou XMLs de nota fiscal (vários de uma vez)"}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Dica: fotografe o cupom esticado, com boa luz e o QR Code nítido. Envie o arquivo original, não pelo WhatsApp.
        </p>
        <input
          ref={input}
          type="file"
          multiple
          accept=".xml,image/jpeg,image/png,image/webp"
          className="hidden"
          onChange={(e) => {
            sendFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      <Card>
        <div className="mb-4 flex flex-wrap gap-1">
          {FILTERS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setFilter(id)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                filter === id ? "bg-emerald-50 text-emerald-700" : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {label}
              {id !== "all" && <span className="ml-1 text-xs text-slate-400">{count(id)}</span>}
            </button>
          ))}
        </div>

        {expenses.isPending ? (
          <p className="text-slate-500">Carregando...</p>
        ) : visible.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-500">
            {all.length === 0 ? "Nenhum lançamento ainda. Envie uma nota ou cupom acima." : "Nada neste filtro."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs tracking-wide text-slate-500 uppercase">
                <tr className="border-b border-slate-200">
                  <th className="py-2 pr-3 font-medium">Data</th>
                  <th className="py-2 pr-3 font-medium">Cliente/Fornecedor</th>
                  <th className="py-2 pr-3 font-medium">Proposta</th>
                  <th className="py-2 pr-3 font-medium">Tipo</th>
                  <th className="py-2 pr-3 font-medium">Funcionário</th>
                  <th className="py-2 pr-3 text-right font-medium">Itens</th>
                  <th className="py-2 pr-3 text-right font-medium">Total</th>
                  <th className="py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((e) => (
                  <Row key={e.id} expense={e} onOpen={() => setSelected(e.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Row({ expense: e, onOpen }: { expense: ExpenseSummary; onOpen: () => void }) {
  const Icon = e.from_spreadsheet ? FileSpreadsheet : SOURCE_ICON[e.source];
  return (
    <tr onClick={onOpen} className="cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50">
      <td className="py-2 pr-3 whitespace-nowrap text-slate-500 tabular-nums">
        {e.issue_date ? formatDate(e.issue_date) : "—"}
      </td>
      <td className="py-2 pr-3">
        <div className="flex items-center gap-2">
          <Icon size={14} className="shrink-0 text-slate-400" />
          <span className="truncate font-medium text-slate-800">
            {e.supplier?.name ?? e.description ?? e.original_filename ?? "—"}
          </span>
        </div>
        {e.issues.length > 0 && e.status !== "confirmed" && (
          <p className="mt-0.5 truncate text-xs text-amber-700" title={e.issues.join("\n")}>
            {e.issues[0]}
            {e.issues.length > 1 && ` (+${e.issues.length - 1})`}
          </p>
        )}
      </td>
      <td className="py-2 pr-3 whitespace-nowrap text-slate-600">{e.proposal ?? ""}</td>
      <td className="py-2 pr-3 text-slate-600">
        <span className={isIncomeType(e.entry_type) ? "font-medium text-emerald-700" : ""}>{e.entry_type}</span>
      </td>
      <td className="py-2 pr-3 text-slate-600">
        {e.employee?.name ?? ""}
        {e.reimbursable && <span className="ml-1 text-xs text-violet-600">(reembolso)</span>}
      </td>
      <td className="py-2 pr-3 text-right text-slate-500 tabular-nums">{e.item_count || ""}</td>
      <td className="py-2 pr-3 text-right font-medium whitespace-nowrap text-slate-900 tabular-nums">
        {e.total_cents !== null ? formatMoney(e.total_cents) : "—"}
      </td>
      <td className="py-2">
        <StatusBadge status={e.status} />
      </td>
    </tr>
  );
}

function ManualForm({ notify, onDone }: { notify: Notify; onDone: (id: number | null) => void }) {
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories, select: companyCategories });
  const employees = useQuery({ queryKey: ["employees"], queryFn: expensesApi.employees });
  const [form, setForm] = useState({
    issue_date: new Date().toISOString().slice(0, 10),
    description: "",
    supplier_name: "",
    amount: "",
    category_id: "",
    employee_id: "",
    reimbursable: false,
    payment_method: "",
    proposal: "",
    entry_type: "",
  });
  const set = (key: keyof typeof form, value: string | boolean) => setForm((f) => ({ ...f, [key]: value }));
  const entryType = form.entry_type || (form.proposal.trim() ? "Custo" : "Despesa");
  const income = isIncomeType(entryType);
  const categoryOptions = categories.data?.filter((c) => c.kind === (income ? "income" : "expense")) ?? [];
  const changeType = (type: string) => {
    // Receita usa categorias de entrada: começa em "Receita de serviços".
    const serviceIncome = categories.data?.find((c) => c.name === "Receita de serviços");
    setForm((f) => ({
      ...f,
      entry_type: type,
      category_id: isIncomeType(type) && serviceIncome ? String(serviceIncome.id) : "",
    }));
  };

  const create = useMutation({
    mutationFn: expensesApi.createManual,
    onSuccess: (expense) => {
      notify(expense.status === "confirmed" ? "Lançamento confirmado." : "Lançamento salvo; confira os avisos.");
      onDone(expense.status === "confirmed" ? null : expense.id);
    },
    onError: (error) => notify(error.message, "error"),
  });

  const amount = parseMoney(form.amount);
  const valid = form.description.trim() && amount !== null && amount > 0;
  const field = "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm";

  return (
    <Card title="Novo lançamento manual">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!valid || amount === null) return;
          create.mutate({
            issue_date: form.issue_date,
            description: form.description.trim(),
            supplier_name: form.supplier_name.trim() || null,
            payment_method: form.payment_method.trim() || null,
            employee_id: form.employee_id ? Number(form.employee_id) : null,
            reimbursable: form.reimbursable,
            proposal: form.proposal.trim() || null,
            entry_type: entryType,
            items: [
              {
                description: form.description.trim(),
                total_cents: amount,
                category_id: form.category_id ? Number(form.category_id) : null,
              },
            ],
          });
        }}
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
      >
        <label className="text-sm text-slate-600 sm:col-span-2">
          Descrição
          <input className={field} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Ex.: Aluguel do galpão, Salário outubro - Ana, Pagamento do cliente" required />
        </label>
        <label className="text-sm text-slate-600">
          Valor (R$)
          <input className={field} value={form.amount} onChange={(e) => set("amount", e.target.value)} placeholder="1.234,56" inputMode="decimal" required />
        </label>
        <label className="text-sm text-slate-600">
          Data
          <input type="date" className={field} value={form.issue_date} onChange={(e) => set("issue_date", e.target.value)} required />
        </label>
        <label className="text-sm text-slate-600">
          Tipo
          <select className={field} value={entryType} onChange={(e) => changeType(e.target.value)}>
            {ENTRY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-slate-600">
          Proposta/obra (opcional)
          <input list="proposals" className={field} value={form.proposal} onChange={(e) => set("proposal", e.target.value)} placeholder="Ex.: P-123" />
        </label>
        <label className="text-sm text-slate-600">
          Categoria
          <select className={field} value={form.category_id} onChange={(e) => set("category_id", e.target.value)}>
            {!income && <option value="">Automática (regras)</option>}
            {categoryOptions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-slate-600">
          {income ? "Cliente" : "Fornecedor"} (opcional)
          <input className={field} value={form.supplier_name} onChange={(e) => set("supplier_name", e.target.value)} />
        </label>
        <label className="text-sm text-slate-600">
          Funcionário (opcional)
          <select className={field} value={form.employee_id} onChange={(e) => set("employee_id", e.target.value)}>
            <option value="">—</option>
            {employees.data
              ?.filter((emp) => emp.active)
              .map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.name}
                </option>
              ))}
          </select>
        </label>
        <label className="text-sm text-slate-600">
          Pagamento (opcional)
          <input className={field} value={form.payment_method} onChange={(e) => set("payment_method", e.target.value)} placeholder="Pix, boleto..." />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-600 sm:col-span-2">
          <input type="checkbox" checked={form.reimbursable} onChange={(e) => set("reimbursable", e.target.checked)} disabled={!form.employee_id} />
          Pago pelo funcionário (reembolsar)
        </label>
        <div className="flex justify-end gap-2 sm:col-span-2">
          <Button type="button" variant="ghost" onClick={() => onDone(null)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={!valid || create.isPending}>
            Salvar lançamento
          </Button>
        </div>
      </form>
    </Card>
  );
}
