import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Lock, Wallet } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { AUTH_EXPIRED_EVENT, authApi } from "../api";
import { Button } from "./ui";

const field = "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none";

/** Mostra o login (ou a criação da primeira conta) até haver uma sessão válida. */
export default function AuthGate({ children }: { children: (username: string) => ReactNode }) {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["auth"], queryFn: authApi.status, retry: false });

  useEffect(() => {
    // Sessão vencida no meio do uso: limpa os dados em cache e volta para o login.
    const expired = () => {
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
      queryClient.invalidateQueries({ queryKey: ["auth"] });
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
  }, [queryClient]);

  if (status.isPending) {
    return (
      <div className="grid min-h-screen place-items-center text-slate-500">
        <Loader2 className="animate-spin" />
      </div>
    );
  }
  if (status.isError) {
    return (
      <div className="grid min-h-screen place-items-center p-4 text-center text-sm text-red-700">
        Não consegui falar com o servidor ({status.error.message}). Ele está rodando na porta 8000?
      </div>
    );
  }
  if (status.data.username) return <>{children(status.data.username)}</>;
  return <LoginForm firstAccess={status.data.setup_required} />;
}

function LoginForm({ firstAccess }: { firstAccess: boolean }) {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => (firstAccess ? authApi.setup(username, password) : authApi.login(username, password)),
    onSuccess: (status) => queryClient.setQueryData(["auth"], status),
    onError: (e) => setError(e.message),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (firstAccess && password !== confirm) return setError("As senhas não conferem.");
    submit.mutate();
  };

  return (
    <div className="grid min-h-screen place-items-center bg-slate-50 px-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 font-semibold text-slate-900">
          <span className="grid size-9 place-items-center rounded-xl bg-emerald-600 text-white">
            <Wallet size={18} />
          </span>
          Finanças
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-900">{firstAccess ? "Criar a primeira conta" : "Entrar"}</h1>
          {firstAccess && (
            <p className="mt-1 text-sm text-slate-500">
              Ainda não há nenhum usuário. O que já está no sistema fica nesta conta. Outras pessoas podem ser
              cadastradas depois e cada uma terá o próprio organizador, sem ver os dados das outras.
            </p>
          )}
        </div>
        <label className="block text-sm text-slate-600">
          Usuário
          <input autoFocus required autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className={`mt-1 ${field}`} />
        </label>
        <label className="block text-sm text-slate-600">
          Senha{firstAccess && " (mínimo 8 caracteres)"}
          <input
            required
            type="password"
            minLength={firstAccess ? 8 : undefined}
            autoComplete={firstAccess ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={`mt-1 ${field}`}
          />
        </label>
        {firstAccess && (
          <label className="block text-sm text-slate-600">
            Repita a senha
            <input required type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className={`mt-1 ${field}`} />
          </label>
        )}
        {error && <p role="alert" className="rounded-lg bg-red-50 p-2 text-sm text-red-700">{error}</p>}
        <Button type="submit" disabled={submit.isPending} className="w-full">
          <Lock size={16} /> {submit.isPending ? "Entrando..." : firstAccess ? "Criar conta e entrar" : "Entrar"}
        </Button>
      </form>
    </div>
  );
}
