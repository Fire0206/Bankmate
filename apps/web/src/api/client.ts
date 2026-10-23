import type { components, paths } from "../generated/api";

type HealthResponse =
  paths["/api/v1/health"]["get"]["responses"][200]["content"]["application/json"];
type CardListResponse =
  paths["/api/v1/cards"]["get"]["responses"][200]["content"]["application/json"];
type DemoSessionResponse = components["schemas"]["DemoSessionResponse"];
type AgentTaskResponse = components["schemas"]["AgentTaskResponse"];
type AuditResponse = components["schemas"]["AgentAuditResponse"];
type CreateTaskRequest =
  paths["/api/v1/agent/tasks"]["post"]["requestBody"]["content"]["application/json"];
type RecentTaskResponse =
  paths["/api/v1/agent/tasks/recent"]["get"]["responses"][200]["content"]["application/json"];
type IdempotencyTaskResponse =
  paths["/api/v1/agent/tasks/by-idempotency-key/{idempotency_key}"]["get"]["responses"][200]["content"]["application/json"];
type IdempotencyOperation =
  paths["/api/v1/agent/tasks/by-idempotency-key/{idempotency_key}"]["get"]["parameters"]["query"]["operation"];
type TransactionsResponse = components["schemas"]["TransactionPageResponse"];
type BillSummaryResponse = components["schemas"]["BillSummaryResponse"];
type SubscriptionListResponse =
  components["schemas"]["SubscriptionListResponse"];
type SubscriptionReminderListResponse =
  components["schemas"]["SubscriptionReminderListResponse"];
type ReminderPreferenceRequest =
  components["schemas"]["ReminderPreferenceRequest"];
type SubscriptionResponse = components["schemas"]["SubscriptionResponse"];
type AccountListResponse = components["schemas"]["AccountBalanceListResponse"];
type PayeeListResponse = components["schemas"]["PayeeListResponse"];
type TransferListResponse = components["schemas"]["TransferListResponse"];
type SplitListResponse = components["schemas"]["SplitBillListResponse"];
type ProductListResponse =
  components["schemas"]["InvestmentProductListResponse"];
type PortfolioResponse = components["schemas"]["InvestmentPortfolioResponse"];
type RiskProfileResponse = components["schemas"]["RiskProfileResponse"];
type RiskQuestionnaireResponse =
  components["schemas"]["RiskQuestionnaireResponse"];
type RiskAssessmentResponse = components["schemas"]["RiskAssessmentResponse"];
type RiskAssessmentRequest = components["schemas"]["RiskAssessmentRequest"];
type OrderListResponse = components["schemas"]["InvestmentOrderListResponse"];
type RecommendationsResponse =
  components["schemas"]["FinancialRecommendationsResponse"];
type PaydayPlanPreviewRequest =
  paths["/api/v1/cashflow/payday-plan-preview"]["post"]["requestBody"]["content"]["application/json"];
type PaydayPlanPreviewResponse =
  components["schemas"]["PaydayPlanPreviewResponse"];
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
  readHealth: () => request<HealthResponse>("/api/v1/health"),
  readSession: () => request<DemoSessionResponse>("/api/v1/demo/session"),
  readCards: () => request<CardListResponse>("/api/v1/cards?limit=100"),
  readTransactions: (month: string) =>
    request<TransactionsResponse>(
      "/api/v1/transactions?month=" + encodeURIComponent(month) + "&limit=100",
    ),
  readBillSummary: (month: string) =>
    request<BillSummaryResponse>(
      "/api/v1/bills/summary?month=" + encodeURIComponent(month),
    ),
  readSubscriptions: () =>
    request<SubscriptionListResponse>("/api/v1/subscriptions"),
  readSubscriptionReminders: () =>
    request<SubscriptionReminderListResponse>(
      "/api/v1/subscriptions/reminders",
    ),
  refreshSubscriptionReminders: () =>
    request<SubscriptionReminderListResponse>(
      "/api/v1/subscriptions/reminders/refresh",
      {
        method: "POST",
      },
    ),
  setSubscriptionReminder: (id: string, body: ReminderPreferenceRequest) =>
    request<SubscriptionResponse>(
      "/api/v1/subscriptions/" +
        encodeURIComponent(id) +
        "/reminder-preference",
      { method: "PUT", body: JSON.stringify(body) },
    ),
  readAccounts: () => request<AccountListResponse>("/api/v1/accounts"),
  readPayees: () => request<PayeeListResponse>("/api/v1/payees"),
  readTransfers: () =>
    request<TransferListResponse>("/api/v1/transfers?limit=50"),
  readSplits: () => request<SplitListResponse>("/api/v1/splits?limit=50"),
  readProducts: () =>
    request<ProductListResponse>("/api/v1/investments/products"),
  readPortfolio: () =>
    request<PortfolioResponse>("/api/v1/investments/portfolio"),
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
  readOrders: () => request<OrderListResponse>("/api/v1/investments/orders"),
  readRecommendations: (month: string) =>
    request<RecommendationsResponse>(
      "/api/v1/financial-insights/recommendations?month=" +
        encodeURIComponent(month),
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
  AgentTaskResponse,
  AuditResponse,
  AccountListResponse,
  BillSummaryResponse,
  CardListResponse,
  CreateTaskRequest,
  DemoSessionResponse,
  HealthResponse,
  OrderListResponse,
  PaydayPlanPreviewRequest,
  PaydayPlanPreviewResponse,
  PayeeListResponse,
  PortfolioResponse,
  ProductListResponse,
  RecommendationsResponse,
  RiskProfileResponse,
  RiskQuestionnaireResponse,
  RiskAssessmentResponse,
  RiskAssessmentRequest,
  SplitListResponse,
  SubscriptionListResponse,
  TaskInputRequest,
  TransactionsResponse,
  TransferListResponse,
};
