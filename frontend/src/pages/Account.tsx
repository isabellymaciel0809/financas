import { useMutation } from "@tanstack/react-query";
import { KeyRound, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { Notify } from "../App";
import { authApi } from "../api";
import { Button, Card } from "../components/ui";

const field = "w-full rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none";

/** Trocar a própria senha e cadastrar outras pessoas da equipe. */
export default function Account({ notify }: { notify: Notify }) {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <ChangePassword notify={notify} />
      <AddUser notify={notify} />
    </div>
  );
}

function ChangePassword({ notify }: { notify: Notify }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const change = useMutation({
    mutationFn: () => authApi.changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      notify("Senha trocada. As sessões abertas em outros aparelhos foram encerradas.");
    },
    onError: (e) => notify(e.message, "error"),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    change.mutate();
  };
  return (
    <Card title="Trocar minha senha">
      <form onSubmit={submit} className="space-y-3">
        <label className="block text-sm text-slate-600">
          Senha atual
          <input required type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} className={`mt-1 ${field}`} />
        </label>
        <label className="block text-sm text-slate-600">
          Nova senha (mínimo 8 caracteres)
          <input required minLength={8} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} className={`mt-1 ${field}`} />
        </label>
        <Button type="submit" disabled={change.isPending}>
          <KeyRound size={16} /> Trocar senha
        </Button>
      </form>
    </Card>
  );
}

function AddUser({ notify }: { notify: Notify }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const add = useMutation({
    mutationFn: () => authApi.addUser(username, password),
    onSuccess: (created) => {
      setUsername("");
      setPassword("");
      notify(`Usuário "${created.username}" cadastrado.`);
    },
    onError: (e) => notify(e.message, "error"),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  return (
    <Card title="Cadastrar outra pessoa">
      <p className="mb-3 text-sm text-slate-500">
        Cada pessoa tem o próprio organizador: começa vazio, e ninguém vê os dados de ninguém. Esqueceu a senha?
        Rode{" "}
        <code className="rounded bg-slate-100 px-1">python scripts/usuario.py NOME</code> no servidor.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <label className="block text-sm text-slate-600">
          Usuário
          <input required autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} className={`mt-1 ${field}`} />
        </label>
        <label className="block text-sm text-slate-600">
          Senha inicial (mínimo 8 caracteres)
          <input required minLength={8} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className={`mt-1 ${field}`} />
        </label>
        <Button type="submit" disabled={add.isPending}>
          <UserPlus size={16} /> Cadastrar
        </Button>
      </form>
    </Card>
  );
}
