import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, FileCode2, Loader2, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Notify } from "../App";
import {
  api,
  companyCategories,
  ENTRY_TYPES,
  expensesApi,
  isIncomeType,
  type ExpenseDetail as Detail,
  type ExpenseItemInput,
} from "../api";
import { Button, Card, SourceBadge } from "../components/ui";
import { centsToInput, formatMoney, parseMoney } from "../format";
import { ProposalOptions, StatusBadge } from "./Expenses";

interface ItemDraft {
  id?: number;
  description: string;
  quantity: string;
  unitPrice: string;
  total: string;
  categoryId: string;
  source?: Detail["items"][number];
}

interface HeaderDraft {
  issue_date: string;
  supplier_name: string;
  supplier_cnpj: string;
  description: string;
  payment_method: string;
  total: string;
  employee_id: string;
  reimbursable: boolean;
  proposal: string;
  entry_type: string;
}

const toDrafts = (d: Detail): { header: HeaderDraft; items: ItemDraft[] } => ({
  header: {
    issue_date: d.issue_date ?? "",
    supplier_name: d.supplier?.name ?? "",
    supplier_cnpj: d.supplier?.cnpj ?? "",
    description: d.description ?? "",
    payment_method: d.payment_method ?? "",
    total: centsToInput(d.total_cents),
    employee_id: d.employee ? String(d.employee.id) : "",
    reimbursable: d.reimbursable,
    proposal: d.proposal ?? "",
    entry_type: d.entry_type,
  },
  items: d.items.map((i) => ({
    id: i.id,
    description: i.description,
    quantity: String(i.quantity).replace(".", ","),
    unitPrice: centsToInput(i.unit_price_cents),
    total: centsToInput(i.total_cents),
    categoryId: i.category ? String(i.category.id) : "",
    source: i,
  })),
});

export default function ExpenseDetail({ id, onBack, notify }: { id: number; onBack: () => void; notify: Notify }) {
  const queryClient = useQueryClient();
  const expense = useQuery({
    queryKey: ["expense", id],
    queryFn: () => expensesApi.get(id),
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 3000 : false),
  });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.categories, select: companyCategories });
  const employees = useQuery({ queryKey: ["employees"], queryFn: expensesApi.employees });

  const [header, setHeader] = useState<HeaderDraft | null>(null);
  const [items, setItems] = useState<ItemDraft[]>([]);
  const [dirty, setDirty] = useState(false);

  const data = expense.data;
  useEffect(() => {
    if (!data || dirty) return;
    const drafts = toDrafts(data);
    setHeader(drafts.header);
    setItems(drafts.items);
  }, [data, dirty]);

  const refresh = (updated: Detail) => {
    queryClient.setQueryData(["expense", id], updated);
    queryClient.invalidateQueries({ queryKey: ["expenses"] });
    queryClient.invalidateQueries({ queryKey: ["items"] });
    setDirty(false);
  };
  const onError = (error: Error) => notify(error.message, "error");

  const save = useMutation({
    mutationFn: () => expensesApi.update(id, buildPayload()),
    onSuccess: (updated) => {
      refresh(updated);
      notify(updated.status === "confirmed" ? "Salvo. Tudo confere: lançamento confirmado." : "Alterações salvas.");
    },
    onError,
  });
  const confirm = useMutation({
    mutationFn: async () => {
      if (dirty) await expensesApi.update(id, buildPayload());
      return expensesApi.confirm(id);
    },
    onSuccess: (updated) => {
      refresh(updated);
      notify("Lançamento confirmado.");
    },
    onError,
  });
  const reprocess = useMutation({
    mutationFn: () => expensesApi.reprocess(id),
    onSuccess: (updated) => {
      refresh(updated);
      notify("Arquivo enviado de novo para a fila de leitura.");
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => expensesApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["expenses"] });
      notify("Lançamento excluído.");
      onBack();
    },
    onError,
  });

  if (expense.isPending || !header) return <p className="text-slate-500">Carregando...</p>;
  if (expense.isError || !data) return <p className="text-red-600">Lançamento não encontrado.</p>;

  function buildPayload() {
    if (!header) return {};
    const parsedItems: ExpenseItemInput[] = items
      .filter((i) => i.description.trim())
      .map((i) => ({
        id: i.id,
        description: i.description.trim(),
        quantity: Number(i.quantity.replace(",", ".")) || 1,
        unit_price_cents: parseMoney(i.unitPrice),
        total_cents: parseMoney(i.total) ?? 0,
        category_id: i.categoryId ? Number(i.categoryId) : null,
      }));
    return {
      issue_date: header.issue_date || null,
      supplier_name: header.supplier_name.trim() || null,
      supplier_cnpj: header.supplier_cnpj.trim() || null,
      description: header.description.trim() || null,
      payment_method: header.payment_method.trim() || null,
      total_cents: parseMoney(header.total),
      employee_id: header.employee_id ? Number(header.employee_id) : null,
      reimbursable: header.reimbursable,
      proposal: header.proposal.trim() || null,
      entry_type: header.entry_type,
      items: parsedItems,
    };
  }

  const setH = (key: keyof HeaderDraft, value: string | boolean) => {
    setHeader((h) => (h ? { ...h, [key]: value } : h));
    setDirty(true);
  };
  const setItem = (index: number, key: keyof ItemDraft, value: string) => {
    setItems((list) => list.map((item, i) => (i === index ? { ...item, [key]: value } : item)));
    setDirty(true);
  };

  const itemsSum = items.reduce((sum, i) => sum + (parseMoney(i.total) ?? 0), 0);
  const expected = data.items_expected_cents ?? parseMoney(header.total);
  const balanced = expected !== null && itemsSum === expected;
  const processing = data.status === "processing";
  const locked = processing || data.status === "duplicate" || data.status === "error";
  const field = "w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm disabled:bg-slate-50";

  return (
    <div className="space-y-4">
      <ProposalOptions />
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" onClick={onBack} aria-label="Voltar">
          <ArrowLeft size={16} />
        </Button>
        <h1 className="text-xl font-semibold text-slate-900">
          Lançamento #{data.id} {data.number && <span className="text-slate-400">· nota nº {data.number}</span>}
        </h1>
        <StatusBadge status={data.status} />
        {data.processing_seconds !== null && (
          <span className="text-xs text-slate-400">lido em {data.processing_seconds.toFixed(0)} s</span>
        )}
        <div className="ml-auto flex flex-wrap gap-2">
          {data.has_file && (
            <Button variant="ghost" onClick={() => reprocess.mutate()} disabled={processing || reprocess.isPending}>
              <RotateCcw size={16} /> Ler de novo
            </Button>
          )}
          <Button variant="ghost" onClick={() => window.confirm("Excluir este lançamento?") && remove.mutate()}>
            <Trash2 size={16} /> Excluir
          </Button>
          <Button variant="ghost" onClick={() => save.mutate()} disabled={!dirty || locked || save.isPending}>
            Salvar
          </Button>
          <Button onClick={() => confirm.mutate()} disabled={locked || data.status === "confirmed" || confirm.isPending}>
            <CheckCircle2 size={16} /> Confirmar
          </Button>
        </div>
      </div>

      {processing && (
        <Card className="flex items-center gap-3 text-sm text-sky-800">
          <Loader2 className="animate-spin" size={18} />
          Lendo o documento (QR Code, OCR e IA). Fotos podem levar alguns minutos neste computador.
        </Card>
      )}

      {data.issues.length > 0 && !processing && (
        <Card className={data.status === "confirmed" ? "" : "border-amber-200 bg-amber-50"}>
          <p className="mb-2 flex items-center gap-2 text-sm font-medium text-amber-900">
            <AlertTriangle size={16} />
            {data.status === "confirmed" ? "Confirmado apesar destes avisos:" : "Confira antes de confirmar:"}
          </p>
          <ul className="list-disc space-y-1 pl-6 text-sm text-amber-900">
            {data.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-5">
        {data.has_file && (
          <Card title="Documento original" className="lg:col-span-2">
            {data.source === "photo" ? (
              <a href={expensesApi.fileUrl(id)} target="_blank" rel="noreferrer">
                <img src={expensesApi.fileUrl(id)} alt="Foto do cupom" className="max-h-[70vh] w-full rounded-lg object-contain" />
              </a>
            ) : (
              <a href={expensesApi.fileUrl(id)} className="flex items-center gap-2 text-sm text-emerald-700 underline">
                <FileCode2 size={16} /> {data.original_filename}
              </a>
            )}
            {data.access_key && <p className="mt-3 text-xs break-all text-slate-500">Chave de acesso: {data.access_key}</p>}
            {data.raw_text && (
              <details className="mt-3 text-xs text-slate-500">
                <summary className="cursor-pointer">Texto lido pelo OCR</summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap">{data.raw_text}</pre>
              </details>
            )}
          </Card>
        )}

        <div className={`space-y-4 ${data.has_file ? "lg:col-span-3" : "lg:col-span-5"}`}>
          <Card title="Dados do lançamento">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-xs text-slate-500">
                Cliente/Fornecedor
                <input className={field} disabled={locked} value={header.supplier_name} onChange={(e) => setH("supplier_name", e.target.value)} />
              </label>
              <label className="text-xs text-slate-500">
                CNPJ
                <input className={field} disabled={locked} value={header.supplier_cnpj} onChange={(e) => setH("supplier_cnpj", e.target.value)} />
              </label>
              <label className="text-xs text-slate-500">
                Proposta/obra
                <input list="proposals" className={field} disabled={locked} value={header.proposal} onChange={(e) => setH("proposal", e.target.value)} placeholder="Ex.: P-123" />
              </label>
              <label className="text-xs text-slate-500">
                Tipo
                <select className={field} disabled={locked} value={header.entry_type} onChange={(e) => setH("entry_type", e.target.value)}>
                  {[...new Set([...ENTRY_TYPES, header.entry_type])].map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-slate-500">
                Data
                <input type="date" className={field} disabled={locked} value={header.issue_date} onChange={(e) => setH("issue_date", e.target.value)} />
              </label>
              <label className="text-xs text-slate-500">
                Valor total (R$)
                <input className={field} disabled={locked || data.source === "manual"} value={header.total} onChange={(e) => setH("total", e.target.value)} />
              </label>
              <label className="text-xs text-slate-500">
                Descrição
                <input className={field} disabled={locked} value={header.description} onChange={(e) => setH("description", e.target.value)} />
              </label>
              <label className="text-xs text-slate-500">
                Pagamento
                <input className={field} disabled={locked} value={header.payment_method} onChange={(e) => setH("payment_method", e.target.value)} />
              </label>
              <label className="text-xs text-slate-500">
                Funcionário
                <select className={field} disabled={locked} value={header.employee_id} onChange={(e) => setH("employee_id", e.target.value)}>
                  <option value="">—</option>
                  {employees.data?.map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.name}
                      {!emp.active && " (inativo)"}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-end gap-2 pb-2 text-sm text-slate-600">
                <input type="checkbox" disabled={locked || !header.employee_id} checked={header.reimbursable} onChange={(e) => setH("reimbursable", e.target.checked)} />
                Pago pelo funcionário (reembolsar)
              </label>
            </div>
          </Card>

          <Card
            title={`Itens (${items.length}${data.declared_item_count ? ` de ${data.declared_item_count} no documento` : ""})`}
            action={
              <span className={`text-sm font-medium ${balanced ? "text-emerald-700" : "text-amber-700"}`}>
                Soma {formatMoney(itemsSum)}
                {expected !== null && !balanced && ` · esperado ${formatMoney(expected)}`}
                {balanced && " ✓"}
              </span>
            }
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-slate-500">
                  <tr>
                    <th className="pb-2 font-medium">Descrição</th>
                    <th className="w-20 pb-2 font-medium">Qtd</th>
                    <th className="w-24 pb-2 font-medium">Unitário</th>
                    <th className="w-24 pb-2 font-medium">Total</th>
                    <th className="w-48 pb-2 font-medium">Categoria</th>
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, index) => (
                    <tr key={item.id ?? `novo-${index}`} className="align-top">
                      <td className="py-1 pr-2">
                        <input className={field} disabled={locked} value={item.description} onChange={(e) => setItem(index, "description", e.target.value)} />
                      </td>
                      <td className="py-1 pr-2">
                        <input className={field} disabled={locked} value={item.quantity} onChange={(e) => setItem(index, "quantity", e.target.value)} />
                      </td>
                      <td className="py-1 pr-2">
                        <input className={field} disabled={locked} value={item.unitPrice} onChange={(e) => setItem(index, "unitPrice", e.target.value)} />
                      </td>
                      <td className="py-1 pr-2">
                        <input className={field} disabled={locked} value={item.total} onChange={(e) => setItem(index, "total", e.target.value)} />
                      </td>
                      <td className="py-1 pr-2">
                        <select
                          className={`${field} ${item.categoryId ? "" : "border-amber-300 bg-amber-50"}`}
                          disabled={locked}
                          value={item.categoryId}
                          onChange={(e) => setItem(index, "categoryId", e.target.value)}
                        >
                          <option value="">— escolher —</option>
                          {categories.data
                            ?.filter((c) => c.kind === (isIncomeType(header.entry_type) ? "income" : "expense"))
                            .map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.icon} {c.name}
                              </option>
                            ))}
                        </select>
                        {item.source && item.source.category && String(item.source.category.id) === item.categoryId && (
                          <div className="mt-1">
                            <SourceBadge source={item.source.categorized_by} confidence={item.source.confidence} />
                          </div>
                        )}
                      </td>
                      <td className="py-1">
                        <button
                          type="button"
                          aria-label="Remover item"
                          disabled={locked}
                          onClick={() => {
                            setItems((list) => list.filter((_, i) => i !== index));
                            setDirty(true);
                          }}
                          className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                        >
                          <X size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!locked && (
              <Button
                variant="ghost"
                className="mt-3"
                onClick={() => {
                  setItems((list) => [...list, { description: "", quantity: "1", unitPrice: "", total: "", categoryId: "" }]);
                  setDirty(true);
                }}
              >
                <Plus size={16} /> Adicionar item
              </Button>
            )}
            <p className="mt-3 text-xs text-slate-400">
              Categorias que você corrigir são memorizadas: na próxima nota com o mesmo item, o sistema já acerta.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}
