import { useEffect, useState } from "react";

import type { components, paths } from "./generated/api";

type Schema = components["schemas"];
type Health =
  paths["/api/v1/health"]["get"]["responses"][200]["content"]["application/json"];
type Cards =
  paths["/api/v1/cards"]["get"]["responses"][200]["content"]["application/json"];
type AgentTask = Schema["AgentTaskResponse"];
type DemoSession = Schema["DemoSessionResponse"];
type AuditResponse = Schema["AgentAuditResponse"];
type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  task?: AgentTask;
};
type ApiState = "checking" | "connected" | "unavailable";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const error =
      typeof payload === "object" && payload !== null && "error" in payload
        ? (payload as { error?: { code?: string; message?: string } }).error
        : undefined;
    throw new ApiError(
      error?.message ?? `API request failed (${response.status}).`,
      response.status,
      error?.code ?? "request_failed",
    );
  }
  return (await response.json()) as T;
}

const readHealth = () => api<Health>("/api/v1/health");
const readSession = () => api<DemoSession>("/api/v1/demo/session");
const readCards = () => api<Cards>("/api/v1/cards?limit=100");
const readTask = (id: string) => api<AgentTask>(`/api/v1/agent/tasks/${id}`);
const readAudit = (id: string) =>
  api<AuditResponse>(`/api/v1/agent/tasks/${id}/audit`);
const sendNewTask = (request_text: string, conversation_id: string) =>
  api<AgentTask>("/api/v1/agent/tasks", {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ request_text, conversation_id }),
  });
const sendTaskInput = (id: string, request_text: string) =>
  api<AgentTask>(`/api/v1/agent/tasks/${id}/input`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ request_text }),
  });
const confirmTask = (task: AgentTask) => {
  const challenge = task.confirmation;
  if (!challenge) throw new Error("No confirmation challenge is pending.");
  return api<AgentTask>(`/api/v1/agent/tasks/${task.id}/confirm`, {
    method: "POST",
    headers: { "Idempotency-Key": challenge.idempotency_key },
    body: JSON.stringify({
      challenge_id: challenge.id,
      parameters_hash: challenge.parameters_hash,
    }),
  });
};
const cancelTask = (id: string) =>
  api<AgentTask>(`/api/v1/agent/tasks/${id}/cancel`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });

function conversationKey(): string {
  const key = "finorch.demo.conversation";
  const saved = sessionStorage.getItem(key);
  if (saved) return saved;
  const id = crypto.randomUUID();
  sessionStorage.setItem(key, id);
  return id;
}

function taskLabel(status: AgentTask["status"]): string {
  return {
    pending: "等待处理",
    planning: "正在规划",
    awaiting_input: "需要补充信息",
    awaiting_confirmation: "等待你的确认",
    running: "执行中",
    completed: "已完成",
    failed: "未完成",
    cancelled: "已取消",
  }[status];
}

function auditLabel(type: string): string {
  const labels: Record<string, string> = {
    "agent.task_created": "创建 Agent 任务",
    "agent.task_input_received": "收到补充信息",
    "agent.tool_execution_succeeded": "受控工具执行成功",
    "agent.tool_execution_failed": "受控工具执行失败",
    "agent.task_state_changed": "任务状态更新",
    "agent.task_cancelled": "取消任务",
    "card.confirmation_requested": "生成确认挑战",
    "card.confirmation_invalidated": "确认挑战失效",
    "card.confirmation_rejected": "拒绝无效确认",
    "card.confirmation_consumed": "消费确认挑战",
    "card.status_changed": "银行卡状态变更",
  };
  return labels[type] ?? type;
}

function timeLabel(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function App() {
  const [conversationId] = useState(conversationKey);
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [apiVersion, setApiVersion] = useState<string | null>(null);
  const [session, setSession] = useState<DemoSession | null>(null);
  const [cards, setCards] = useState<Cards["items"]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [activeTask, setActiveTask] = useState<AgentTask | null>(null);
  const [audit, setAudit] = useState<AuditResponse["events"]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [healthRetry, setHealthRetry] = useState(0);

  useEffect(() => {
    let active = true;
    readHealth()
      .then((data) => {
        if (!active) return;
        setApiState(data.status === "ok" ? "connected" : "unavailable");
        setApiVersion(data.version);
      })
      .catch(() => {
        if (!active) return;
        setApiState("unavailable");
        setApiVersion(null);
      });
    return () => {
      active = false;
    };
  }, [healthRetry]);

  useEffect(() => {
    let active = true;
    Promise.all([readSession(), readCards()])
      .then(([demo, cardPage]) => {
        if (!active) return;
        setSession(demo);
        setCards(cardPage.items);
      })
      .catch((error: unknown) => {
        if (active)
          setPageError(
            error instanceof Error ? error.message : "读取演示数据失败。",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const activeTaskId = activeTask?.id;
  const activeTaskVersion = activeTask?.version;

  useEffect(() => {
    let active = true;
    if (!activeTaskId) return;
    readAudit(activeTaskId)
      .then((data) => {
        if (active) setAudit(data.events);
      })
      .catch(() => {
        if (active) setAudit([]);
      });
    return () => {
      active = false;
    };
  }, [activeTaskId, activeTaskVersion]);

  function setTask(task: AgentTask) {
    setActiveTask(task);
    setMessages((current) => {
      const row: Message = {
        id: `task-${task.id}`,
        role: "assistant",
        text: task.message,
        task,
      };
      return [
        ...current.filter((message) => message.task?.id !== task.id),
        row,
      ];
    });
  }

  async function refreshCards() {
    setCards((await readCards()).items);
  }

  async function retryConnection() {
    setPageError(null);
    setLoading(true);
    setHealthRetry((value) => value + 1);
    try {
      const [demo, cardPage] = await Promise.all([readSession(), readCards()]);
      setSession(demo);
      setCards(cardPage.items);
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "读取演示数据失败。",
      );
    } finally {
      setLoading(false);
    }
  }

  async function sendMessage(text = draft) {
    const value = text.trim();
    if (!value || busy) return;
    setDraft("");
    setBusy(true);
    setPageError(null);
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", text: value },
    ]);
    try {
      const current = activeTask;
      const task =
        current &&
        ["awaiting_input", "awaiting_confirmation"].includes(current.status)
          ? await sendTaskInput(current.id, value)
          : await sendNewTask(value, conversationId);
      setTask(task);
      if (task.status === "completed") await refreshCards();
    } catch (error) {
      setPageError(
        error instanceof Error ? error.message : "请求没有完成，请重试。",
      );
    } finally {
      setBusy(false);
    }
  }

  async function confirm(task: AgentTask) {
    if (!task.confirmation || busy) return;
    setBusy(true);
    setPageError(null);
    try {
      setTask(await confirmTask(task));
      await refreshCards();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          setTask(await readTask(task.id));
          await refreshCards();
        } catch {
          setPageError(error.message);
        }
      } else {
        setPageError(
          error instanceof Error ? error.message : "确认没有完成，请重试。",
        );
      }
    } finally {
      setBusy(false);
    }
  }

  async function cancel(task: AgentTask) {
    if (busy) return;
    setBusy(true);
    try {
      setTask(await cancelTask(task.id));
      await refreshCards();
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "取消任务失败。");
    } finally {
      setBusy(false);
    }
  }

  const connectionText = {
    checking: "检查 API 连接",
    connected: "API 已连接",
    unavailable: "API 不可用",
  }[apiState];

  return (
    <main className="min-h-screen px-4 pb-8 pt-4 sm:px-7 sm:pt-6">
      <div className="mx-auto max-w-[1380px]">
        <header className="topbar flex flex-wrap items-center justify-between gap-4 rounded-2xl px-4 py-3 sm:px-6">
          <a
            className="brand-lockup flex items-center gap-3"
            href="#home"
            aria-label="FinOrch 首页"
          >
            <span className="brand-mark" aria-hidden="true">
              F
            </span>
            <span>
              <b>FinOrch</b>
              <small>AI BANKING AGENT</small>
            </span>
          </a>
          <div className="flex flex-wrap items-center gap-3">
            <span className="phase-badge">PHASE 1B · CARD AGENT</span>
            <span
              className={`connection-badge connection-${apiState}`}
              aria-live="polite"
            >
              <i />
              {connectionText}
              {apiVersion ? <small>v{apiVersion}</small> : null}
            </span>
            <a
              className="docs-link"
              href="http://127.0.0.1:8000/docs"
              target="_blank"
              rel="noreferrer"
            >
              API 文档 ↗
            </a>
          </div>
        </header>

        <section
          id="home"
          className="intro-band mt-7 grid gap-5 lg:grid-cols-[1fr_auto] lg:items-end"
        >
          <div>
            <p className="eyebrow">
              CARD CONTROL / SYNTHETIC BANKING ENVIRONMENT
            </p>
            <h1 className="mt-3 max-w-3xl text-3xl font-semibold leading-[1.12] tracking-[-0.055em] text-[#17312e] sm:text-4xl lg:text-[3.1rem]">
              让每一次卡片操作，
              <span className="heading-accent">都有迹可循。</span>
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[#677773] sm:text-base">
              用自然语言查询、冻结或解冻模拟银行卡。变更由服务端校验，并在执行前等待你的确认。
            </p>
          </div>
          <div className="session-panel flex items-center gap-3 rounded-2xl px-4 py-3">
            <span className="session-avatar" aria-hidden="true">
              {session?.display_name.slice(0, 1) ?? "D"}
            </span>
            <span>
              <b>{session?.display_name ?? "读取演示身份…"}</b>
              <small>
                {session
                  ? `${session.environment.toUpperCase()} · ${session.dataset_version}`
                  : "合成数据环境"}
              </small>
            </span>
            <span className="mode-badge">
              {activeTask?.provider_mode ?? session?.agent_provider ?? "fake"}
            </span>
          </div>
        </section>

        {pageError ? (
          <div className="error-banner mt-5" role="alert">
            <span>{pageError}</span>
            <button onClick={() => void retryConnection()} type="button">
              重试连接
            </button>
          </div>
        ) : null}

        <div className="workspace-grid mt-7 grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(350px,0.75fr)]">
          <section
            className="panel-shell conversation-panel flex min-h-[690px] flex-col"
            aria-labelledby="conversation-title"
          >
            <div className="panel-header flex items-center justify-between gap-4 px-5 py-4 sm:px-7">
              <div className="flex items-center gap-3">
                <span className="agent-emblem" aria-hidden="true">
                  F
                </span>
                <div>
                  <h2 id="conversation-title">与 FinOrch 对话</h2>
                  <small>银行卡管理 · 演示任务</small>
                </div>
              </div>
              <span className="provider-tag">
                <i />
                {activeTask?.provider_mode === "openai-compatible"
                  ? "OpenAI-compatible"
                  : "Fake Provider"}
              </span>
            </div>

            <div
              className="conversation-scroll flex-1 space-y-5 px-4 py-5 sm:px-7"
              aria-live="polite"
            >
              {messages.length === 0 ? (
                <div className="welcome-card mx-auto mt-8 max-w-xl rounded-3xl p-6 sm:p-8">
                  <span className="welcome-symbol" aria-hidden="true">
                    ↗
                  </span>
                  <p className="eyebrow mt-5">CONTROLLED CARD TOOLS</p>
                  <h3 className="mt-2 text-xl font-semibold text-[#1a3832]">
                    你好，{session?.display_name ?? "演示用户"}
                  </h3>
                  <p className="mt-2 max-w-md text-sm leading-6 text-[#71807b]">
                    先查看自己的模拟卡片。冻结和解冻会先生成确认卡片，确认后服务端才会更新状态。
                  </p>
                  <div className="mt-6 grid gap-2 sm:grid-cols-2">
                    {[
                      "查看我的银行卡",
                      "冻结尾号 1042 的卡",
                      "把尾号 4318 的卡解冻",
                    ].map((prompt) => (
                      <button
                        className="prompt-chip"
                        key={prompt}
                        onClick={() => void sendMessage(prompt)}
                        type="button"
                      >
                        <span>↗</span>
                        {prompt}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((message) => (
                  <article
                    className={`message-row message-${message.role}`}
                    key={message.id}
                  >
                    {message.role === "assistant" ? (
                      <span className="message-avatar" aria-hidden="true">
                        F
                      </span>
                    ) : null}
                    <div className="message-content">
                      <div className={`message-bubble bubble-${message.role}`}>
                        <p>{message.text}</p>
                      </div>
                      {message.task ? (
                        <TaskDetails
                          task={message.task}
                          busy={busy}
                          onConfirm={() => void confirm(message.task!)}
                          onCancel={() => void cancel(message.task!)}
                        />
                      ) : null}
                    </div>
                    {message.role === "user" ? (
                      <span
                        className="message-avatar user-avatar"
                        aria-hidden="true"
                      >
                        {session?.display_name.slice(0, 1) ?? "D"}
                      </span>
                    ) : null}
                  </article>
                ))
              )}
              {busy ? (
                <div className="agent-thinking" role="status">
                  <span>F</span>
                  <i />
                  <i />
                  <i />
                  正在与服务端协作…
                </div>
              ) : null}
            </div>

            <form
              className="composer-wrap px-4 pb-4 pt-3 sm:px-7 sm:pb-6"
              onSubmit={(event) => {
                event.preventDefault();
                void sendMessage();
              }}
            >
              {activeTask?.status === "awaiting_input" ? (
                <p className="composer-hint">补充信息将继续当前任务。</p>
              ) : null}
              {activeTask?.status === "awaiting_confirmation" ? (
                <p className="composer-hint">
                  修改请求会使当前确认失效，并重新生成操作方案。
                </p>
              ) : null}
              <label className="sr-only" htmlFor="agent-request">
                描述银行卡操作
              </label>
              <div className="composer-box flex items-end gap-3 rounded-2xl p-2.5 pl-4">
                <textarea
                  id="agent-request"
                  maxLength={1000}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void sendMessage();
                    }
                  }}
                  placeholder="试试：冻结尾号 1042 的卡"
                  rows={1}
                  value={draft}
                />
                <button
                  className="send-button"
                  disabled={busy || !draft.trim()}
                  type="submit"
                  aria-label="发送请求"
                >
                  {busy ? "…" : "↑"}
                </button>
              </div>
              <div className="composer-foot">
                <span>Enter 发送 · Shift + Enter 换行</span>
                <span>Fake Provider 不调用外部模型</span>
              </div>
            </form>
          </section>

          <aside className="right-rail space-y-5">
            <section className="panel-shell" aria-labelledby="cards-title">
              <div className="panel-header flex items-center justify-between px-5 py-4">
                <div>
                  <p className="eyebrow">SYNTHETIC ACCOUNTS</p>
                  <h2 id="cards-title">我的银行卡</h2>
                </div>
                <button
                  className="refresh-button"
                  onClick={() => void refreshCards()}
                  type="button"
                >
                  ↻ 刷新
                </button>
              </div>
              <div className="space-y-3 p-4">
                {loading ? (
                  <p className="empty-note">正在读取模拟卡片…</p>
                ) : null}
                {!loading && cards.length === 0 ? (
                  <p className="empty-note">当前身份下没有卡片。</p>
                ) : null}
                {cards.map((card, index) => (
                  <article
                    className={`bank-card bank-card-${index % 3}`}
                    key={card.id}
                  >
                    <div className="flex items-start justify-between">
                      <span className="card-chip">
                        <i />
                        <i />
                        <i />
                        <i />
                      </span>
                      <span className={`card-state state-${card.status}`}>
                        <i />
                        {card.status === "active" ? "正常" : "已冻结"}
                      </span>
                    </div>
                    <div className="mt-5 flex items-end justify-between">
                      <div>
                        <b>{card.label}</b>
                        <small>•••• {card.card_suffix}</small>
                      </div>
                      <span className="card-watermark">F</span>
                    </div>
                  </article>
                ))}
              </div>
              <div className="rail-foot">
                <span>数据集 {session?.dataset_version ?? "—"}</span>
                <span>{cards.length} 张合成卡片</span>
              </div>
            </section>

            <section className="panel-shell" aria-labelledby="workflow-title">
              <div className="panel-header px-5 py-4">
                <p className="eyebrow">SERVER WORKFLOW</p>
                <div className="mt-1 flex items-center justify-between gap-3">
                  <h2 id="workflow-title">当前任务</h2>
                  {activeTask ? (
                    <span className={`task-state task-${activeTask.status}`}>
                      {taskLabel(activeTask.status)}
                    </span>
                  ) : null}
                </div>
              </div>
              {!activeTask ? (
                <p className="empty-note px-5 pb-5">
                  完成一次对话后，这里会显示数据库中的任务和工具步骤。
                </p>
              ) : (
                <div className="px-5 pb-5">
                  <p className="task-message">{activeTask.message}</p>
                  <ol className="workflow-list mt-4 space-y-3">
                    {activeTask.steps.map((step) => (
                      <li className="workflow-step" key={step.id}>
                        <span className={`step-marker step-${step.status}`}>
                          {step.status === "succeeded"
                            ? "✓"
                            : step.status === "failed"
                              ? "!"
                              : "·"}
                        </span>
                        <span className="min-w-0 flex-1">
                          <b>
                            {step.tool_name ??
                              (step.step_type === "planner"
                                ? "任务规划"
                                : "用户补充")}
                          </b>
                          <small>{step.summary}</small>
                        </span>
                        <time>
                          {timeLabel(
                            step.step_type === "planner"
                              ? activeTask.updated_at
                              : activeTask.created_at,
                          )}
                        </time>
                      </li>
                    ))}
                  </ol>
                  <div className="task-meta">
                    <span>Task {activeTask.id.slice(0, 8)}…</span>
                    <span>
                      {activeTask.provider_mode === "fake"
                        ? "确定性 Fake Provider"
                        : "OpenAI-compatible"}
                    </span>
                  </div>
                </div>
              )}
            </section>

            <section className="panel-shell" aria-labelledby="audit-title">
              <div className="panel-header flex items-center justify-between px-5 py-4">
                <div>
                  <p className="eyebrow">APPEND-ONLY RECORD</p>
                  <h2 id="audit-title">本次审计摘要</h2>
                </div>
                <span className="audit-lock" aria-label="审计记录只读">
                  ▤
                </span>
              </div>
              {!activeTask || audit.length === 0 ? (
                <p className="empty-note px-5 pb-5">
                  任务事件和实际卡片变更会记录在这里。
                </p>
              ) : (
                <ol className="audit-list px-5 pb-4">
                  {audit.map((entry) => (
                    <li className="audit-row" key={entry.id}>
                      <span className={`audit-mark outcome-${entry.outcome}`}>
                        {entry.outcome === "succeeded" ? "✓" : "·"}
                      </span>
                      <span className="min-w-0 flex-1">
                        <b>{auditLabel(entry.event_type)}</b>
                        <small>
                          {entry.before_state?.status &&
                          entry.after_state?.status
                            ? `${entry.before_state.status} → ${entry.after_state.status}`
                            : entry.outcome}
                        </small>
                      </span>
                      <time dateTime={entry.occurred_at}>
                        {timeLabel(entry.occurred_at)}
                      </time>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </aside>
        </div>

        <footer className="page-footer mt-6 flex flex-wrap items-center justify-between gap-3 border-t pt-4 text-xs">
          <span>FinOrch · 模拟银行环境 · 不连接真实账户、银行卡或支付系统</span>
          <span>当前交付卡片 Agent 垂直切片；其他五大场景仍在规划中。</span>
        </footer>
      </div>
    </main>
  );
}

function TaskDetails({
  task,
  busy,
  onConfirm,
  onCancel,
}: {
  task: AgentTask;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const challenge = task.confirmation;
  return (
    <div className="task-details mt-2 space-y-2">
      <div className="task-inline-status">
        <span className={`task-state task-${task.status}`}>
          {taskLabel(task.status)}
        </span>
        <span>
          {task.provider_mode === "fake"
            ? "Fake Provider · 本地确定性模式"
            : "OpenAI-compatible Provider"}
        </span>
      </div>
      {challenge ? (
        <section className="confirmation-card" aria-label="待确认的银行卡操作">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="eyebrow">ACTION REVIEW</p>
              <h3>
                确认{challenge.target_status === "frozen" ? "冻结" : "解冻"}
                银行卡
              </h3>
            </div>
            <span className="risk-tag">需要确认</span>
          </div>
          <div className="confirmation-impact mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-xl px-3 py-3">
            <span>
              <small>卡片</small>
              <b>{challenge.card_label}</b>
              <small>•••• {challenge.card_suffix}</small>
            </span>
            <span className="impact-arrow">→</span>
            <span className="text-right">
              <small>状态变更</small>
              <b>
                {challenge.current_status} → {challenge.target_status}
              </b>
              <small>卡片版本 {challenge.card_version}</small>
            </span>
          </div>
          <p className="challenge-expiry">
            挑战有效至 {timeLabel(challenge.expires_at)}
            。确认仅作用于当前合成数据。
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="confirm-button"
              disabled={busy}
              onClick={onConfirm}
              type="button"
            >
              {busy
                ? "处理中…"
                : `确认${challenge.target_status === "frozen" ? "冻结" : "解冻"}`}
            </button>
            <button
              className="cancel-button"
              disabled={busy}
              onClick={onCancel}
              type="button"
            >
              取消操作
            </button>
          </div>
        </section>
      ) : null}
      {task.error_code ? (
        <p className="task-error">
          {task.error_code} · {task.message}
        </p>
      ) : null}
      {task.steps.some((step) => step.result_data?.items) ? (
        <p className="tool-result-note">
          <span>✓</span> 已从服务端读取卡片数据，右侧卡片状态以数据库返回为准。
        </p>
      ) : null}
    </div>
  );
}
