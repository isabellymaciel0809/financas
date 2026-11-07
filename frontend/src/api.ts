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
