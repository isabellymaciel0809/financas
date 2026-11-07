import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileDown, FileUp } from "lucide-react";
import { useRef, useState } from "react";
import type { Notify } from "../App";
import { companySheetApi, downloadBlob, type SpreadsheetImportResult } from "../api";
import { Card } from "./ui";

/** Importar o histórico da planilha da empresa e devolvê-la atualizada com os lançamentos novos. */
export default function CompanySheet({ notify, onClose }: { notify: Notify; onClose: () => void }) {
  const queryClient = useQueryClient();
  const importInput = useRef<HTMLInputElement>(null);
  const updateInput = useRef<HTMLInputElement>(null);
  const [month, setMonth] = useState("");
  const [imported, setImported] = useState<SpreadsheetImportResult | null>(null);

  const importSheet = useMutation({
    mutationFn: companySheetApi.import,
    onSuccess: (result) => {
      setImported(result);
      ["expenses", "items", "proposals"].forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }));
      notify(`${result.imported} linha(s) carregada(s) da aba "${result.sheet}".`);
    },
    onError: (error) => notify(error.message, "error"),
  });

  const updateSheet = useMutation({
    mutationFn: (file: File) => companySheetApi.update(file, month || undefined),
    onSuccess: (result) => {
      downloadBlob(result.blob, result.filename);
      notify(
        result.added
          ? `Planilha atualizada: ${result.added} linha(s) nova(s)` +
              (result.alreadyInSheet ? `, ${result.alreadyInSheet} já estava(m) lá.` : ".")
          : "Nada novo para acrescentar: a planilha já tem todos os lançamentos confirmados.",
      );
    },
    onError: (error) => notify(error.message, "error"),
  });

  const pick = (input: HTMLInputElement | null) => input?.click();
  const box = "flex flex-col gap-3 rounded-xl border border-slate-200 p-4";

  return (
    <Card
      title="Planilha da empresa"
      action={
        <button onClick={onClose} className="text-sm text-slate-500 hover:text-slate-800">
          Fechar
        </button>
      }
    >
      <p className="mb-4 text-sm text-slate-500">
        A planilha precisa ter as colunas <strong>Data</strong>, <strong>Descrição</strong> e <strong>Valor</strong>; Mês,
        Cliente/Fornecedor, Proposta e Tipo são usados quando existirem. O sistema encontra a tabela sozinho, mesmo com
        título acima.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <div className={box}>
          <div>
            <p className="font-medium text-slate-800">1. Carregar dados da planilha</p>
            <p className="text-sm text-slate-500">
              Traz o histórico para o sistema. Cada linha vira um lançamento confirmado. Linhas que já foram importadas
              ou que já estão lançadas no sistema não são duplicadas.
            </p>
          </div>
          <button
            onClick={() => pick(importInput.current)}
            disabled={importSheet.isPending}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:bg-emerald-300"
          >
            <FileUp size={16} /> {importSheet.isPending ? "Carregando..." : "Escolher planilha (.xlsx)"}
          </button>
          {imported && (
            <p className="text-xs text-slate-600">
              {imported.imported} carregada(s), {imported.duplicates} já importada(s) antes
              {imported.already_in_system > 0 && `, ${imported.already_in_system} já lançada(s) no sistema`}
              {imported.skipped > 0 &&
                `, ${imported.skipped} ignorada(s) (linhas ${imported.skipped_rows.join(", ")}${imported.skipped > imported.skipped_rows.length ? "..." : ""}: total ou sem data/valor)`}
              .
            </p>
          )}
          <input
            ref={importInput}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) importSheet.mutate(file);
              e.target.value = "";
            }}
          />
        </div>

        <div className={box}>
          <div>
            <p className="font-medium text-slate-800">2. Atualizar a planilha da empresa</p>
            <p className="text-sm text-slate-500">
              Envie a planilha atual e baixe ela mesma com os lançamentos confirmados que ainda não estão lá. Outras
              abas, formatação e totais são mantidos. O arquivo original não é alterado.
            </p>
          </div>
          <label className="text-xs text-slate-500">
            Só deste mês (opcional)
            <input
              type="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              className="mt-1 block rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
            />
          </label>
          <button
            onClick={() => pick(updateInput.current)}
            disabled={updateSheet.isPending}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-slate-200 ring-inset hover:bg-slate-50"
          >
            <FileDown size={16} /> {updateSheet.isPending ? "Gerando..." : "Escolher planilha e baixar atualizada"}
          </button>
          <input
            ref={updateInput}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) updateSheet.mutate(file);
              e.target.value = "";
            }}
          />
        </div>
      </div>
    </Card>
  );
}
