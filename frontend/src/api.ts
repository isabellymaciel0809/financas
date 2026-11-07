// Tipos espelham os schemas Pydantic do backend (app/schemas.py).

export type CategorizedBy = "manual" | "memory" | "rule" | "llm" | "none";

export interface Category {
  id: number;
  name: string;
  kind: "expense" | "income";
  color: string;
  icon: string;
}

export interface Transaction {
  id: number;
  date: string;
  description: string;
  amount_cents: number;
  category: Category | null;
  categorized_by: CategorizedBy;
  confidence: number | null;
}

export interface CategorizationStats {
  memory: number;
  rule: number;
  llm: number;
  none: number;
}

export interface ImportResult {
  filename: string;
  source_format: string;
  imported: number;
  duplicates: number;
  categorization: CategorizationStats;
  llm_queued: number;
  llm_error: string | null;
}

export interface CategorizationJobStatus {
  running: boolean;
  pending: number;
  last_categorized: number;
  last_error: string | null;
}

export interface DashboardSummary {
  month: string;
  income_cents: number;
  expense_cents: number;
  balance_cents: number;
  transaction_count: number;
  expenses_by_category: {
    category_id: number | null;
    name: string;
    color: string;
    icon: string;
    total_cents: number;
  }[];
  monthly: { month: string; income_cents: number; expense_cents: number }[];
  categorized_by: CategorizationStats;
}

export interface Health {
  status: string;
  llm_provider: string;
  llm_model: string | null;
  llm_available: boolean;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  answer: string;
  tool_calls: { name: string; arguments: Record<string, unknown> }[];
  unverified_values: string[];
}

export interface TransactionFilters {
  month?: string;
  category_id?: number;
  needs_review?: boolean;
  search?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let message = `Erro ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* resposta sem JSON */
    }
    throw new Error(message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const api = {
  health: () => request<Health>("/health"),
  categories: () => request<Category[]>("/categories"),
  summary: (month?: string) =>
    request<DashboardSummary>(`/dashboard/summary${month ? `?month=${month}` : ""}`),
  transactions: (filters: TransactionFilters) => {
    const params = new URLSearchParams({ limit: "500" });
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== "" && value !== false) params.set(key, String(value));
    });
    return request<{ items: Transaction[]; total: number }>(`/transactions?${params}`);
  },
  updateCategory: (id: number, categoryId: number | null) =>
    request<{ transaction: Transaction; similar_updated: number }>(
      `/transactions/${id}`,
      json("PATCH", { category_id: categoryId }),
    ),
  deleteTransaction: (id: number) =>
    request<void>(`/transactions/${id}`, { method: "DELETE" }),
  categorizePending: () =>
    request<{ queued: number }>("/transactions/categorize", { method: "POST" }),
  categorizationStatus: () => request<CategorizationJobStatus>("/transactions/categorize/status"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportResult>("/imports", { method: "POST", body: form });
  },
  loadDemo: () => request<ImportResult>("/demo", { method: "POST" }),
  chat: (messages: ChatMessage[]) =>
    request<ChatResponse>("/assistant/chat", json("POST", { messages })),
};

// --- Lançamentos de despesa (notas, cupons e manuais) ----------------------------------------

export type ExpenseStatus = "processing" | "needs_review" | "confirmed" | "duplicate" | "error";
export type ExpenseSource = "nfe_xml" | "photo" | "manual";

export interface Employee {
  id: number;
  name: string;
  role: string | null;
  active: boolean;
}

export interface ExpenseItem {
  id: number;
  position: number;
  code: string | null;
  description: string;
  ncm: string | null;
  quantity: number;
  unit: string | null;
  unit_price_cents: number | null;
  total_cents: number;
  category: Category | null;
  categorized_by: CategorizedBy;
  confidence: number | null;
}

export interface ExpenseSummary {
  id: number;
  source: ExpenseSource;
  status: ExpenseStatus;
  issue_date: string | null;
  description: string | null;
  supplier: { id: number; cnpj: string | null; name: string } | null;
  employee: Employee | null;
  reimbursable: boolean;
  proposal: string | null;
  entry_type: string;
  from_spreadsheet: boolean;
  number: string | null;
  total_cents: number | null;
  original_filename: string | null;
  issues: string[];
  item_count: number;
  processing_seconds: number | null;
}

export interface ExpenseDetail extends ExpenseSummary {
  access_key: string | null;
  model: string | null;
  series: string | null;
  payment_method: string | null;
  declared_item_count: number | null;
  items_expected_cents: number | null;
  raw_text: string | null;
  has_file: boolean;
  items: ExpenseItem[];
}

export interface ExpenseItemInput {
  id?: number;
  description: string;
  total_cents: number;
  quantity?: number;
  unit?: string | null;
  unit_price_cents?: number | null;
  category_id?: number | null;
}

export interface ExpenseUpdate {
  description?: string | null;
  issue_date?: string | null;
  total_cents?: number | null;
  payment_method?: string | null;
  supplier_name?: string | null;
  supplier_cnpj?: string | null;
  employee_id?: number | null;
  reimbursable?: boolean;
  proposal?: string | null;
  entry_type?: string;
  items?: ExpenseItemInput[];
}

export interface ManualExpenseInput {
  issue_date: string;
  description: string;
  items: ExpenseItemInput[];
  supplier_name?: string | null;
  payment_method?: string | null;
  employee_id?: number | null;
  reimbursable?: boolean;
  proposal?: string | null;
  entry_type?: string | null;
}

// Coluna "Tipo" da planilha da empresa (o campo aceita outros valores).
export const ENTRY_TYPES = ["Custo", "Despesas", "Estoque", "Receita", "Caixa"];
export const isIncomeType = (type: string) => type === "Receita";

export const expensesApi = {
  list: (status?: ExpenseStatus) =>
    request<ExpenseSummary[]>(`/expenses${status ? `?status=${status}` : ""}`),
  get: (id: number) => request<ExpenseDetail>(`/expenses/${id}`),
  upload: (files: File[], proposal?: string, entryType?: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    if (proposal) form.append("proposal", proposal);
    if (entryType) form.append("entry_type", entryType);
    return request<ExpenseSummary[]>("/expenses/upload", { method: "POST", body: form });
  },
  createManual: (data: ManualExpenseInput) =>
    request<ExpenseDetail>("/expenses", json("POST", data)),
  update: (id: number, data: ExpenseUpdate) =>
    request<ExpenseDetail>(`/expenses/${id}`, json("PATCH", data)),
  confirm: (id: number) => request<ExpenseDetail>(`/expenses/${id}/confirm`, { method: "POST" }),
  reprocess: (id: number) =>
    request<ExpenseDetail>(`/expenses/${id}/reprocess`, { method: "POST" }),
  remove: (id: number) => request<void>(`/expenses/${id}`, { method: "DELETE" }),
  proposals: () => request<string[]>("/expenses/proposals"),
  fileUrl: (id: number) => `/api/expenses/${id}/file`,
  exportUrl: (month?: string) =>
    `/api/expenses/export.xlsx${month ? `?month=${month}` : ""}`,
  employees: () => request<Employee[]>("/employees"),
  createEmployee: (data: Omit<Employee, "id">) =>
    request<Employee>("/employees", json("POST", data)),
  updateEmployee: (id: number, data: Omit<Employee, "id">) =>
    request<Employee>(`/employees/${id}`, json("PUT", data)),
};

// --- Tela de itens (todos os itens de todas as notas) ----------------------------------------

export interface ItemRow {
  id: number;
  expense_id: number;
  expense_status: ExpenseStatus;
  issue_date: string | null;
  counterpart: string | null;
  proposal: string | null;
  description: string;
  entry_type: string;
  category: Category | null;
  quantity: number;
  unit: string | null;
  unit_price_cents: number | null;
  total_cents: number;
}

export interface GroupTotal {
  name: string;
  total_cents: number;
  count: number;
}

export interface ItemsReport {
  items: ItemRow[];
  count: number;
  total_cents: number;
  by_type: GroupTotal[];
  by_category: GroupTotal[];
  truncated: boolean;
}

export interface ItemFilters {
  month?: string;
  proposal?: string;
  entry_type?: string;
  category_id?: number;
  search?: string;
  only_confirmed?: boolean;
}

const itemParams = (filters: ItemFilters) => {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "" && value !== false) params.set(key, String(value));
  });
  return params.toString();
};

export const itemsApi = {
  list: (filters: ItemFilters) => request<ItemsReport>(`/expenses/items?${itemParams(filters)}`),
  exportUrl: (filters: ItemFilters) => `/api/expenses/items/export.xlsx?${itemParams(filters)}`,
};

// --- Planilha que a empresa já usa -------------------------------------------------------------

export interface SpreadsheetImportResult {
  sheet: string;
  imported: number;
  duplicates: number;
  skipped: number;
  skipped_rows: number[];
}

export interface SpreadsheetUpdateResult {
  blob: Blob;
  filename: string;
  added: number;
  alreadyInSheet: number;
}

export const companySheetApi = {
  /** Carrega o histórico da planilha da empresa para o sistema. */
  import: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<SpreadsheetImportResult>("/expenses/spreadsheet/import", { method: "POST", body: form });
  },
  /** Devolve a própria planilha da empresa com os lançamentos novos no fim da tabela. */
  update: async (file: File, month?: string): Promise<SpreadsheetUpdateResult> => {
    const form = new FormData();
    form.append("file", file);
    if (month) form.append("month", month);
    const response = await fetch("/api/expenses/spreadsheet/update", { method: "POST", body: form });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : `Erro ${response.status}`);
    }
    const disposition = response.headers.get("content-disposition") ?? "";
    return {
      blob: await response.blob(),
      filename: /filename="([^"]+)"/.exec(disposition)?.[1] ?? "planilha-atualizada.xlsx",
      added: Number(response.headers.get("x-rows-added") ?? 0),
      alreadyInSheet: Number(response.headers.get("x-rows-already-in-sheet") ?? 0),
    };
  },
};

export const downloadBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
};
