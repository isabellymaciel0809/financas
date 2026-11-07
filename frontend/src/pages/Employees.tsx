import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { useState } from "react";
import type { Notify } from "../App";
import { expensesApi, type Employee } from "../api";
import { Button, Card } from "../components/ui";

export default function Employees({ notify }: { notify: Notify }) {
  const queryClient = useQueryClient();
  const employees = useQuery({ queryKey: ["employees"], queryFn: expensesApi.employees });
  const [name, setName] = useState("");
  const [role, setRole] = useState("");

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["employees"] });
  const create = useMutation({
    mutationFn: () => expensesApi.createEmployee({ name: name.trim(), role: role.trim() || null, active: true }),
    onSuccess: (employee) => {
      refresh();
      setName("");
      setRole("");
      notify(`${employee.name} cadastrado(a).`);
    },
    onError: (error) => notify(error.message, "error"),
  });
  const toggle = useMutation({
    mutationFn: (e: Employee) => expensesApi.updateEmployee(e.id, { name: e.name, role: e.role, active: !e.active }),
    onSuccess: refresh,
    onError: (error) => notify(error.message, "error"),
  });

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Funcionários</h1>
        <p className="text-sm text-slate-500">
          Ligue lançamentos a funcionários: folha, benefícios e despesas pagas por eles (reembolso). A exportação
          em Excel traz uma aba com quanto devolver a cada um.
        </p>
      </div>

      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) create.mutate();
          }}
          className="flex flex-wrap gap-2"
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nome"
            className="min-w-48 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm"
          />
          <input
            value={role}
            onChange={(e) => setRole(e.target.value)}
            placeholder="Cargo (opcional)"
            className="min-w-40 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm"
          />
          <Button type="submit" disabled={!name.trim() || create.isPending}>
            <UserPlus size={16} /> Adicionar
          </Button>
        </form>
      </Card>

      <Card>
        {employees.data?.length ? (
          <ul className="divide-y divide-slate-100">
            {employees.data.map((e) => (
              <li key={e.id} className="flex items-center justify-between py-2">
                <div>
                  <p className={`font-medium ${e.active ? "text-slate-800" : "text-slate-400 line-through"}`}>{e.name}</p>
                  {e.role && <p className="text-xs text-slate-500">{e.role}</p>}
                </div>
                <Button variant="ghost" onClick={() => toggle.mutate(e)}>
                  {e.active ? "Desativar" : "Reativar"}
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-6 text-center text-sm text-slate-500">Nenhum funcionário cadastrado.</p>
        )}
      </Card>
    </div>
  );
}
