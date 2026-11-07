import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, CheckCircle2, FileUp } from "lucide-react";
import { useRef, useState } from "react";
import type { Notify, OnQueued, Page } from "../App";
import { api, type ImportResult } from "../api";
import { Button, Card, StatsPills } from "../components/ui";

const FORMAT_LABELS: Record<string, string> = {
  nubank_conta: "Nubank (conta)",
  nubank_cartao: "Nubank (cartão)",
  inter: "Banco Inter",
  ofx: "OFX",
  csv_generico: "CSV genérico",
};

export default function ImportPage({ onNavigate, notify, onQueued }: {
  onNavigate: (p: Page) => void;
  notify: Notify;
  onQueued: OnQueued;
}) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const upload = useMutation({
    mutationFn: api.upload,
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries();
      onQueued(data.llm_queued);
    },
    onError: (error) => notify(error.message, "error"),
  });

  const handleFiles = (files: FileList | null) => {
    if (files?.[0]) upload.mutate(files[0]);
  };

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-2xl font-semibold text-slate-900">Importar extrato</h1>

      <Card>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            handleFiles(e.dataTransfer.files);
          }}
          onClick={() => input.current?.click()}
          className={`cursor-pointer rounded-2xl border-2 border-dashed p-10 text-center transition-colors ${
            dragging ? "border-emerald-500 bg-emerald-50" : "border-slate-200 hover:border-emerald-400"
          }`}
        >
          <FileUp className="mx-auto mb-3 text-emerald-600" size={32} />
          <p className="font-medium text-slate-800">
            {upload.isPending ? "Importando e categorizando..." : "Arraste o arquivo aqui ou clique para escolher"}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            CSV do Nubank (conta ou cartão), Banco Inter, outros bancos com colunas de data, descrição e valor, ou OFX.
          </p>
          <input
            ref={input}
            type="file"
            accept=".csv,.ofx,text/csv"
            className="hidden"
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
        <p className="mt-3 text-xs text-slate-400">
          O arquivo é processado no seu próprio servidor. Com o Ollama, nem a categorização sai da sua máquina.
          Reimportar o mesmo extrato não duplica transações.
        </p>
      </Card>

      {result && (
        <Card>
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 shrink-0 text-emerald-600" />
            <div className="flex-1 space-y-3">
              <div>
                <p className="font-medium text-slate-900">
                  {result.imported} transações importadas de {result.filename}
                </p>
                <p className="text-sm text-slate-500">
                  Formato detectado: {FORMAT_LABELS[result.source_format] ?? result.source_format}
                  {result.duplicates > 0 && ` · ${result.duplicates} já existiam e foram ignoradas`}
                </p>
              </div>
              <StatsPills stats={result.categorization} />
              {result.llm_queued > 0 ? (
                <p className="flex items-start gap-2 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">
                  <Bot size={16} className="mt-0.5 shrink-0" />
                  {result.llm_queued} transação(ões) sem pista nas regras foram enviadas para a IA, que roda em
                  segundo plano. Você pode continuar usando o app; avisamos quando terminar.
                </p>
              ) : (
                result.categorization.none > 0 && (
                  <p className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                    Nenhuma IA disponível agora: {result.categorization.none} transação(ões) ficaram pendentes para
                    você revisar.
                  </p>
                )
              )}
              <div className="flex gap-2">
                <Button onClick={() => onNavigate("transactions")}>Ver transações</Button>
                <Button variant="ghost" onClick={() => onNavigate("dashboard")}>Ir para a visão geral</Button>
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
