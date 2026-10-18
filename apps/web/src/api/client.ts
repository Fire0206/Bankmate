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
  readAudit: (id: string) =>
    request<AuditResponse>(
      "/api/v1/agent/tasks/" + encodeURIComponent(id) + "/audit",
    ),
  createTask: (body: CreateTaskRequest) =>
    request<AgentTaskResponse>("/api/v1/agent/tasks", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey() },
      body: JSON.stringify(body),
    }),
  provideTaskInput: (id: string, body: TaskInputRequest) =>
    request<AgentTaskResponse>(
      "/api/v1/agent/tasks/" + encodeURIComponent(id) + "/input",
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey() },
        body: JSON.stringify(body),
      },
    ),
  confirmTask: (task: AgentTaskResponse) => {
    const challenge = task.confirmation;
    if (!challenge) throw new Error("No confirmation is pending.");
    const body: ConfirmationRequest = {
      challenge_id: challenge.id,
      parameters_hash: challenge.parameters_hash,
    };
    return request<AgentTaskResponse>(
      "/api/v1/agent/tasks/" + encodeURIComponent(task.id) + "/confirm",
      {
        method: "POST",
        headers: { "Idempotency-Key": challenge.idempotency_key },
        body: JSON.stringify(body),
      },
    );
  },
  cancelTask: (id: string) =>
    request<AgentTaskResponse>(
      "/api/v1/agent/tasks/" + encodeURIComponent(id) + "/cancel",
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey() },
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
