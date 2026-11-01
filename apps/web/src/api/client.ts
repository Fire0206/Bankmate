import type { components, paths } from "../generated/api";

type HealthResponse =
  paths["/api/v1/health"]["get"]["responses"][200]["content"]["application/json"];
type CardListResponse =
  paths["/api/v1/cards"]["get"]["responses"][200]["content"]["application/json"];
type DemoSessionResponse = components["schemas"]["DemoSessionResponse"];
type AgentTaskResponse = components["schemas"]["AgentTaskResponse"];
type HandoffResponse = components["schemas"]["HandoffResponse"];
type AuditResponse = components["schemas"]["AgentAuditResponse"];
type AccountBalanceListResponse =
  components["schemas"]["AccountBalanceListResponse"];
type AccountListResponse = AccountBalanceListResponse;
type BillSummaryResponse = components["schemas"]["BillSummaryResponse"];
type TransactionPageResponse = components["schemas"]["TransactionPageResponse"];
type SubscriptionListResponse =
  components["schemas"]["SubscriptionListResponse"];
type SubscriptionReminderListResponse =
  components["schemas"]["SubscriptionReminderListResponse"];
type ReminderPreferenceRequest =
  components["schemas"]["ReminderPreferenceRequest"];
type SubscriptionResponse = components["schemas"]["SubscriptionResponse"];
type TransferListResponse = components["schemas"]["TransferListResponse"];
type SplitBillListResponse = components["schemas"]["SplitBillListResponse"];
type PayeeListResponse = components["schemas"]["PayeeListResponse"];
type PayeeCreateRequest = components["schemas"]["PayeeCreateRequest"];
type PayeeResponse = components["schemas"]["PayeeResponse"];
type TransferDestinationListResponse =
  components["schemas"]["TransferDestinationListResponse"];
type AgentTaskHistoryResponse =
  components["schemas"]["AgentTaskHistoryResponse"];
type RiskProfileResponse = components["schemas"]["RiskProfileResponse"];
type RiskQuestionnaireResponse =
  components["schemas"]["RiskQuestionnaireResponse"];
type RiskAssessmentResponse = components["schemas"]["RiskAssessmentResponse"];
type RiskAssessmentRequest = components["schemas"]["RiskAssessmentRequest"];
type InvestmentProductListResponse =
  components["schemas"]["InvestmentProductListResponse"];
type InvestmentPortfolioResponse =
  components["schemas"]["InvestmentPortfolioResponse"];
type InvestmentOrderListResponse =
  components["schemas"]["InvestmentOrderListResponse"];
type OrderListResponse = InvestmentOrderListResponse;
type ProductListResponse = InvestmentProductListResponse;
type PortfolioResponse = InvestmentPortfolioResponse;
type SplitListResponse = SplitBillListResponse;
type TransactionsResponse = TransactionPageResponse;
type RecommendationsResponse =
  components["schemas"]["FinancialRecommendationsResponse"];
type PaydayPlanPreviewRequest =
  paths["/api/v1/cashflow/payday-plan-preview"]["post"]["requestBody"]["content"]["application/json"];
type PaydayPlanPreviewResponse =
  components["schemas"]["PaydayPlanPreviewResponse"];
type CreateTaskRequest =
  paths["/api/v1/agent/tasks"]["post"]["requestBody"]["content"]["application/json"];
type RecentTaskResponse =
  paths["/api/v1/agent/tasks/recent"]["get"]["responses"][200]["content"]["application/json"];
type IdempotencyTaskResponse =
  paths["/api/v1/agent/tasks/by-idempotency-key/{idempotency_key}"]["get"]["responses"][200]["content"]["application/json"];
type IdempotencyOperation =
  paths["/api/v1/agent/tasks/by-idempotency-key/{idempotency_key}"]["get"]["parameters"]["query"]["operation"];
type TaskInputRequest =
  paths["/api/v1/agent/tasks/{task_id}/input"]["post"]["requestBody"]["content"]["application/json"];
type ConfirmationRequest =
  paths["/api/v1/agent/tasks/{task_id}/confirm"]["post"]["requestBody"]["content"]["application/json"];

type ApiErrorBody = components["schemas"]["ApiErrorResponse"]["error"];

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId: string | null,
    readonly details: ApiErrorBody["details"],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiBaseUrl + path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const apiError =
      typeof payload === "object" &&
      payload !== null &&
      "error" in payload &&
      typeof payload.error === "object" &&
      payload.error !== null
        ? (payload.error as ApiErrorBody)
        : null;
    throw new ApiError(
      apiError?.message ?? "服务暂时无法处理这项请求。",
      response.status,
      apiError?.code ?? "request_failed",
      apiError?.request_id ?? null,
      apiError?.details ?? [],
    );
  }
  return payload as T;
}

function idempotencyKey(): string {
  return crypto.randomUUID();
}

export const apiClient = {
  readHandoff: (taskId: string) =>
    request<HandoffResponse | null>(
      `/api/v1/agent/tasks/${encodeURIComponent(taskId)}/handoff`,
    ),
  requestHandoff: (
    taskId: string,
    reason: "user_requested" | "partial_success" | "cannot_continue",
  ) =>
    request<HandoffResponse>(
      `/api/v1/agent/tasks/${encodeURIComponent(taskId)}/handoff`,
      { method: "POST", body: JSON.stringify({ reason }) },
    ),
  readHealth: () => request<HealthResponse>("/api/v1/health"),
  readSession: () => request<DemoSessionResponse>("/api/v1/demo/session"),
  readCards: () => request<CardListResponse>("/api/v1/cards?limit=100"),
  readAccounts: () => request<AccountBalanceListResponse>("/api/v1/accounts"),
  readBillSummary: (month?: string, category?: string) => {
    const query = new URLSearchParams();
    if (month) query.set("month", month);
    if (category) query.set("category", category);
    return request<BillSummaryResponse>(
      "/api/v1/bills/summary" + (query.size ? "?" + query.toString() : ""),
    );
  },
  readTransactions: (
    params?:
      | string
      | {
          month?: string;
          category?: string;
          merchant?: string;
          direction?: "income" | "expense";
          offset?: number;
          limit?: number;
        },
  ) => {
    if (typeof params === "string") params = { month: params };
    const query = new URLSearchParams();
    if (params?.month) query.set("month", params.month);
    if (params?.category) query.set("category", params.category);
    if (params?.merchant) query.set("merchant", params.merchant);
    if (params?.direction) query.set("direction", params.direction);
    if (params?.offset !== undefined)
      query.set("offset", String(params.offset));
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    return request<TransactionPageResponse>(
      "/api/v1/transactions" + (query.size ? "?" + query.toString() : ""),
    );
  },
  readSubscriptions: () =>
    request<SubscriptionListResponse>("/api/v1/subscriptions"),
  readSubscriptionReminders: () =>
    request<SubscriptionReminderListResponse>(
      "/api/v1/subscriptions/reminders",
    ),
  refreshSubscriptionReminders: () =>
    request<SubscriptionReminderListResponse>(
      "/api/v1/subscriptions/reminders/refresh",
      { method: "POST" },
    ),
  setSubscriptionReminder: (id: string, body: ReminderPreferenceRequest) =>
    request<SubscriptionResponse>(
      "/api/v1/subscriptions/" +
        encodeURIComponent(id) +
        "/reminder-preference",
      { method: "PUT", body: JSON.stringify(body) },
    ),
  readPayees: () => request<PayeeListResponse>("/api/v1/payees"),
  readTransferDestinations: () =>
    request<TransferDestinationListResponse>("/api/v1/transfer-destinations"),
  createPayee: (body: PayeeCreateRequest) =>
    request<PayeeResponse>("/api/v1/payees", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  readTransfers: (limit = 50) =>
    request<TransferListResponse>("/api/v1/transfers?limit=" + String(limit)),
  readSplits: (limit = 50) =>
    request<SplitBillListResponse>("/api/v1/splits?limit=" + String(limit)),
  readRiskProfile: () =>
    request<RiskProfileResponse>("/api/v1/investments/profile"),
  readRiskQuestionnaire: () =>
    request<RiskQuestionnaireResponse>(
      "/api/v1/investments/risk-assessment/questionnaire",
    ),
  readLatestRiskAssessment: () =>
    request<RiskAssessmentResponse | null>(
      "/api/v1/investments/risk-assessment/latest",
    ),
  submitRiskAssessment: (body: RiskAssessmentRequest, key: string) =>
    request<RiskAssessmentResponse>("/api/v1/investments/risk-assessment", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(body),
    }),
  readInvestmentProducts: () =>
    request<InvestmentProductListResponse>("/api/v1/investments/products"),
  readProducts: () =>
    request<InvestmentProductListResponse>("/api/v1/investments/products"),
  readInvestmentPortfolio: () =>
    request<InvestmentPortfolioResponse>("/api/v1/investments/portfolio"),
  readPortfolio: () =>
    request<InvestmentPortfolioResponse>("/api/v1/investments/portfolio"),
  readInvestmentOrders: () =>
    request<InvestmentOrderListResponse>("/api/v1/investments/orders"),
  readOrders: () =>
    request<InvestmentOrderListResponse>("/api/v1/investments/orders"),
  readRecommendations: (month?: string) =>
    request<RecommendationsResponse>(
      "/api/v1/financial-insights/recommendations?month=" +
        encodeURIComponent(month ?? ""),
    ),
  previewPaydayPlan: (body: PaydayPlanPreviewRequest) =>
    request<PaydayPlanPreviewResponse>("/api/v1/cashflow/payday-plan-preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  readTask: (id: string) =>
    request<AgentTaskResponse>("/api/v1/agent/tasks/" + encodeURIComponent(id)),
  readRecentTask: (conversationId: string) =>
    request<RecentTaskResponse>(
      "/api/v1/agent/tasks/recent?conversation_id=" +
        encodeURIComponent(conversationId),
    ),
  readTaskHistory: (limit = 20) =>
    request<AgentTaskHistoryResponse>(
      "/api/v1/agent/tasks/history?limit=" + String(limit),
    ),
  readTaskByIdempotencyKey: (
    key: string,
    conversationId: string,
    operation: IdempotencyOperation,
    taskId?: string,
  ) => {
    const params = new URLSearchParams({
      conversation_id: conversationId,
      operation,
    });
    if (taskId) params.set("task_id", taskId);
    return request<IdempotencyTaskResponse>(
      "/api/v1/agent/tasks/by-idempotency-key/" +
        encodeURIComponent(key) +
        "?" +
        params.toString(),
    );
  },
  readAudit: (id: string) =>
    request<AuditResponse>(
      "/api/v1/agent/tasks/" + encodeURIComponent(id) + "/audit",
    ),
  createTask: (body: CreateTaskRequest, key = idempotencyKey()) =>
    request<AgentTaskResponse>("/api/v1/agent/tasks", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(body),
    }),
  provideTaskInput: (
    id: string,
    body: TaskInputRequest,
    key = idempotencyKey(),
  ) =>
    request<AgentTaskResponse>(
      "/api/v1/agent/tasks/" + encodeURIComponent(id) + "/input",
      {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify(body),
      },
    ),
  confirmTask: (
    taskId: string,
    challengeId: string,
    parametersHash: string,
    key: string,
    verificationCode?: string,
  ) => {
    const body: ConfirmationRequest = {
      challenge_id: challengeId,
      parameters_hash: parametersHash,
      verification_code: verificationCode,
    };
    return request<AgentTaskResponse>(
      "/api/v1/agent/tasks/" + encodeURIComponent(taskId) + "/confirm",
      {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify(body),
      },
    );
  },
  cancelTask: (id: string, key = idempotencyKey()) =>
    request<AgentTaskResponse>(
      "/api/v1/agent/tasks/" + encodeURIComponent(id) + "/cancel",
      {
        method: "POST",
        headers: { "Idempotency-Key": key },
      },
    ),
};

export type {
  AccountBalanceListResponse,
  AccountListResponse,
  AgentTaskResponse,
  AgentTaskHistoryResponse,
  AuditResponse,
  BillSummaryResponse,
  CardListResponse,
  CreateTaskRequest,
  DemoSessionResponse,
  HealthResponse,
  InvestmentOrderListResponse,
  InvestmentPortfolioResponse,
  InvestmentProductListResponse,
  OrderListResponse,
  PayeeListResponse,
  PayeeCreateRequest,
  PaydayPlanPreviewRequest,
  PaydayPlanPreviewResponse,
  PortfolioResponse,
  ProductListResponse,
  RecommendationsResponse,
  ReminderPreferenceRequest,
  RiskAssessmentRequest,
  RiskAssessmentResponse,
  RiskProfileResponse,
  RiskQuestionnaireResponse,
  SplitBillListResponse,
  SplitListResponse,
  SubscriptionListResponse,
  SubscriptionReminderListResponse,
  SubscriptionResponse,
  TaskInputRequest,
  TransactionPageResponse,
  TransactionsResponse,
  TransferListResponse,
  TransferDestinationListResponse,
};
