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
  ) => {
    const body: ConfirmationRequest = {
      challenge_id: challengeId,
      parameters_hash: parametersHash,
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
  CardListResponse,
  DemoSessionResponse,
  HealthResponse,
};
