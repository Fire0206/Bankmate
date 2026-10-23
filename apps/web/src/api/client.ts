import type { components, paths } from "../generated/api";
import {
  demoAccounts,
  demoBills,
  demoCards,
  demoHealth,
  demoOrders,
  demoPayees,
  demoPortfolio,
  demoProducts,
  demoRiskProfile,
  demoSession,
  demoSplits,
  demoSubscriptions,
  demoTransactions,
  demoTransfers,
} from "../demoData";

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
export const staticPreviewMode =
  import.meta.env.VITE_STATIC_DEMO === "true" &&
  import.meta.env.MODE === "production";

function preview<T>(value: T): Promise<T> {
  return Promise.resolve(structuredClone(value));
}

function previewWrite(): Promise<never> {
  return Promise.reject(
    new ApiError(
      "当前是静态展示包。页面可以浏览，资金类操作请连接本地 API 后体验。",
      503,
      "static_preview_read_only",
      null,
      [],
    ),
  );
}

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
  readHealth: () =>
    staticPreviewMode
      ? preview(demoHealth)
      : request<HealthResponse>("/api/v1/health"),
  readSession: () =>
    staticPreviewMode
      ? preview(demoSession)
      : request<DemoSessionResponse>("/api/v1/demo/session"),
  readCards: () =>
    staticPreviewMode
      ? preview(demoCards)
      : request<CardListResponse>("/api/v1/cards?limit=100"),
  readAccounts: () =>
    staticPreviewMode
      ? preview(demoAccounts)
      : request<AccountBalanceListResponse>("/api/v1/accounts"),
  readBillSummary: (month?: string, category?: string) => {
    if (staticPreviewMode) {
      const data = structuredClone(demoBills);
      if (month) data.month = month;
      if (category) {
        data.selected_category = category;
        data.selected_category_expense_minor =
          data.categories.find((item) => item.category === category)
            ?.amount_minor ?? 0;
      }
      return preview(data);
    }
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
    if (staticPreviewMode) {
      const items = demoTransactions.items.filter((item) => {
        if (params?.category && item.category !== params.category) return false;
        if (params?.merchant && !item.merchant.includes(params.merchant))
          return false;
        if (params?.direction && item.direction !== params.direction)
          return false;
        return true;
      });
      const offset = params?.offset ?? 0;
      const limit = params?.limit ?? items.length;
      return preview({
        ...demoTransactions,
        items: items.slice(offset, offset + limit),
        total: items.length,
        offset,
        limit,
        next_offset: offset + limit < items.length ? offset + limit : null,
      } as TransactionPageResponse);
    }
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
    staticPreviewMode
      ? preview(demoSubscriptions)
      : request<SubscriptionListResponse>("/api/v1/subscriptions"),
  readSubscriptionReminders: () =>
    staticPreviewMode
      ? preview<SubscriptionReminderListResponse>({ items: [] })
      : request<SubscriptionReminderListResponse>(
          "/api/v1/subscriptions/reminders",
        ),
  refreshSubscriptionReminders: () =>
    staticPreviewMode
      ? preview<SubscriptionReminderListResponse>({ items: [] })
      : request<SubscriptionReminderListResponse>(
          "/api/v1/subscriptions/reminders/refresh",
          { method: "POST" },
        ),
  setSubscriptionReminder: (id: string, body: ReminderPreferenceRequest) =>
    staticPreviewMode
      ? previewWrite()
      : request<SubscriptionResponse>(
          "/api/v1/subscriptions/" +
            encodeURIComponent(id) +
            "/reminder-preference",
          { method: "PUT", body: JSON.stringify(body) },
        ),
  readPayees: () =>
    staticPreviewMode
      ? preview(demoPayees)
      : request<PayeeListResponse>("/api/v1/payees"),
  readTransfers: (limit = 50) =>
    staticPreviewMode
      ? preview(demoTransfers)
      : request<TransferListResponse>(
          "/api/v1/transfers?limit=" + String(limit),
        ),
  readSplits: (limit = 50) =>
    staticPreviewMode
      ? preview(demoSplits)
      : request<SplitBillListResponse>("/api/v1/splits?limit=" + String(limit)),
  readRiskProfile: () =>
    staticPreviewMode
      ? preview(demoRiskProfile)
      : request<RiskProfileResponse>("/api/v1/investments/profile"),
  readRiskQuestionnaire: () =>
    staticPreviewMode
      ? preview<RiskQuestionnaireResponse>({
          questionnaire_version: "demo-v1",
          questions: [],
          notice: "静态预览不提交风险测评。",
        })
      : request<RiskQuestionnaireResponse>(
          "/api/v1/investments/risk-assessment/questionnaire",
        ),
  readLatestRiskAssessment: () =>
    staticPreviewMode
      ? Promise.resolve(null)
      : request<RiskAssessmentResponse | null>(
          "/api/v1/investments/risk-assessment/latest",
        ),
  submitRiskAssessment: (body: RiskAssessmentRequest, key: string) =>
    staticPreviewMode
      ? previewWrite()
      : request<RiskAssessmentResponse>("/api/v1/investments/risk-assessment", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: JSON.stringify(body),
        }),
  readInvestmentProducts: () =>
    staticPreviewMode
      ? preview(demoProducts)
      : request<InvestmentProductListResponse>("/api/v1/investments/products"),
  readProducts: () =>
    staticPreviewMode
      ? preview(demoProducts)
      : request<InvestmentProductListResponse>("/api/v1/investments/products"),
  readInvestmentPortfolio: () =>
    staticPreviewMode
      ? preview(demoPortfolio)
      : request<InvestmentPortfolioResponse>("/api/v1/investments/portfolio"),
  readPortfolio: () =>
    staticPreviewMode
      ? preview(demoPortfolio)
      : request<InvestmentPortfolioResponse>("/api/v1/investments/portfolio"),
  readInvestmentOrders: () =>
    staticPreviewMode
      ? preview(demoOrders)
      : request<InvestmentOrderListResponse>("/api/v1/investments/orders"),
  readOrders: () =>
    staticPreviewMode
      ? preview(demoOrders)
      : request<InvestmentOrderListResponse>("/api/v1/investments/orders"),
  readRecommendations: (month?: string) => {
    if (staticPreviewMode) {
      const targetMonth = month ?? demoBills.month;
      const items = demoBills.anomalies.slice(0, 3).map((item, index) => ({
        id: "static-recommendation-" + String(index + 1),
        category: "bill_review" as const,
        priority: index === 0 ? ("high" as const) : ("medium" as const),
        title: "核对 " + item.merchant + " 的扣费",
        explanation: item.anomaly_reason ?? "该交易命中了演示规则提示。",
        amount_minor: item.amount_minor,
        currency: item.currency,
        source_transaction_ids: [item.id],
      }));
      return preview<RecommendationsResponse>({
        month: targetMonth,
        generated_at: new Date().toISOString(),
        items,
      });
    }
    return request<RecommendationsResponse>(
      "/api/v1/financial-insights/recommendations?month=" +
        encodeURIComponent(month ?? ""),
    );
  },
  previewPaydayPlan: (body: PaydayPlanPreviewRequest) => {
    if (staticPreviewMode) {
      const account = demoAccounts.items[0];
      const remaining = account.balance_minor - body.transfer_amount_minor;
      const afterReserve = remaining - body.reserve_amount_minor;
      return preview<PaydayPlanPreviewResponse>({
        account_label: account.label,
        currency: account.currency,
        month: body.month ?? demoBills.month,
        account_balance_minor: account.balance_minor,
        monthly_income_minor: demoBills.income_minor,
        monthly_expense_minor: demoBills.expense_minor,
        recipient_name: body.recipient_name,
        transfer_amount_minor: body.transfer_amount_minor,
        reserve_amount_minor: body.reserve_amount_minor,
        remaining_after_transfer_minor: remaining,
        investment_budget_minor: Math.max(0, afterReserve),
        reserve_shortfall_minor: Math.max(0, -afterReserve),
      });
    }
    return request<PaydayPlanPreviewResponse>(
      "/api/v1/cashflow/payday-plan-preview",
      { method: "POST", body: JSON.stringify(body) },
    );
  },
  readTask: (id: string) =>
    staticPreviewMode
      ? previewWrite()
      : request<AgentTaskResponse>(
          "/api/v1/agent/tasks/" + encodeURIComponent(id),
        ),
  readRecentTask: (conversationId: string) =>
    staticPreviewMode
      ? Promise.resolve(null)
      : request<RecentTaskResponse>(
          "/api/v1/agent/tasks/recent?conversation_id=" +
            encodeURIComponent(conversationId),
        ),
  readTaskByIdempotencyKey: (
    key: string,
    conversationId: string,
    operation: IdempotencyOperation,
    taskId?: string,
  ) => {
    if (staticPreviewMode) return Promise.resolve(null);
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
    staticPreviewMode
      ? previewWrite()
      : request<AuditResponse>(
          "/api/v1/agent/tasks/" + encodeURIComponent(id) + "/audit",
        ),
  createTask: (body: CreateTaskRequest, key = idempotencyKey()) =>
    staticPreviewMode
      ? previewWrite()
      : request<AgentTaskResponse>("/api/v1/agent/tasks", {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: JSON.stringify(body),
        }),
  provideTaskInput: (
    id: string,
    body: TaskInputRequest,
    key = idempotencyKey(),
  ) =>
    staticPreviewMode
      ? previewWrite()
      : request<AgentTaskResponse>(
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
    if (staticPreviewMode) return previewWrite();
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
    staticPreviewMode
      ? previewWrite()
      : request<AgentTaskResponse>(
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
};
