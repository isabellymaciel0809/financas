import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, Database, SendHorizontal, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type ChatMessage, type ChatResponse } from "../api";
import { Button, Card } from "../components/ui";

const SUGGESTIONS = [
  "Quanto gastei este mês?",
  "Quais foram meus 5 maiores gastos do mês passado?",
  "Quanto gastei com alimentação nos últimos 3 meses?",
  "Como minhas despesas evoluíram nos últimos meses?",
];

const TOOL_LABELS: Record<string, string> = {
  resumo_financeiro: "Resumo do período",
  buscar_transacoes: "Busca de transações",
  evolucao_mensal: "Evolução mensal",
};

interface Turn extends ChatMessage {
  toolCalls?: ChatResponse["tool_calls"];
  error?: boolean;
}

export default function Assistant() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  const send = useMutation({
    mutationFn: (history: ChatMessage[]) => api.chat(history),
    onSuccess: (data) =>
      setTurns((t) => [...t, { role: "assistant", content: data.answer, toolCalls: data.tool_calls }]),
    onError: (error) =>
      setTurns((t) => [...t, { role: "assistant", content: error.message, error: true }]),
  });

  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [turns, send.isPending]);

  const ask = (question: string) => {
    const text = question.trim();
    if (!text || send.isPending) return;
    // Erros não voltam para a LLM como se fossem respostas dela.
    const userTurn: ChatMessage = { role: "user", content: text };
    const history: ChatMessage[] = [...turns.filter((t) => !t.error), userTurn]
      .slice(-12)
      .map(({ role, content }): ChatMessage => ({ role, content }));
    setTurns((t) => [...t, userTurn]);
    setInput("");
    send.mutate(history);
  };

  const llm = health.data;
  const unavailable = llm && !llm.llm_available;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Assistente</h1>
        <p className="text-sm text-slate-500">
          Pergunte sobre suas finanças. A IA consulta seus dados por meio de ferramentas e não
          inventa valores: cada resposta mostra quais consultas foram feitas.
        </p>
      </div>

      {unavailable && (
        <Card className="border-amber-200 bg-amber-50">
          <p className="text-sm text-amber-900">
            O assistente precisa de uma LLM, e nenhuma está disponível agora
            {llm.llm_provider === "ollama" && (
              <>
                . Instale o <a className="underline" href="https://ollama.com/download" target="_blank" rel="noreferrer">Ollama</a>{" "}
                e rode <code className="rounded bg-amber-100 px-1">ollama pull {llm.llm_model}</code>. É gratuito e roda no
                seu computador
              </>
            )}
            .
          </p>
        </Card>
      )}

      <Card className="flex min-h-[28rem] flex-col">
        <div className="flex-1 space-y-4 overflow-y-auto">
          {turns.length === 0 ? (
            <div className="py-6 text-center">
              <div className="mx-auto mb-3 grid size-12 place-items-center rounded-2xl bg-emerald-50 text-emerald-600">
                <Bot />
              </div>
              <p className="mb-4 text-sm text-slate-500">Experimente perguntar:</p>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => ask(s)}
                    disabled={unavailable}
                    className="rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700 hover:bg-emerald-50 hover:text-emerald-700 disabled:opacity-50"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            turns.map((turn, i) => <Bubble key={i} turn={turn} />)
          )}
          {send.isPending && (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <Bot size={16} /> Consultando seus dados...
            </div>
          )}
          <div ref={bottom} />
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
          className="mt-4 flex gap-2 border-t border-slate-100 pt-4"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ex.: quanto gastei com Uber em outubro?"
            maxLength={2000}
            disabled={unavailable}
            className="flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-emerald-500 disabled:bg-slate-50"
          />
          <Button type="submit" disabled={!input.trim() || send.isPending || unavailable} aria-label="Enviar">
            <SendHorizontal size={16} />
          </Button>
        </form>
      </Card>
    </div>
  );
}

function Bubble({ turn }: { turn: Turn }) {
  const isUser = turn.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <span
        className={`grid size-8 shrink-0 place-items-center rounded-full ${
          isUser ? "bg-slate-200 text-slate-600" : "bg-emerald-100 text-emerald-700"
        }`}
      >
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </span>
      <div className={`max-w-[85%] space-y-2 ${isUser ? "text-right" : ""}`}>
        <div
          className={`inline-block rounded-2xl px-4 py-2 text-left text-sm whitespace-pre-wrap ${
            isUser
              ? "bg-emerald-600 text-white"
              : turn.error
                ? "bg-red-50 text-red-700"
                : "bg-slate-100 text-slate-800"
          }`}
        >
          {turn.content}
        </div>
        {turn.toolCalls && turn.toolCalls.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {turn.toolCalls.map((call, i) => (
              <span
                key={i}
                title={JSON.stringify(call.arguments)}
                className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-xs text-slate-500 ring-1 ring-slate-200"
              >
                <Database size={11} />
                {TOOL_LABELS[call.name] ?? call.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
