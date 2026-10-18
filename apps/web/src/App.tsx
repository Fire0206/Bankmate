import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiClient } from "./api/client";
import type {
  AgentTaskResponse,
  AuditResponse,
  CardListResponse,
  DemoSessionResponse,
} from "./api/client";
import { AppIcon } from "./components/AppIcon";
import { CardList } from "./components/CardList";
import { ConfirmationCard } from "./components/ConfirmationCard";
import { Navigation } from "./components/Navigation";
import { TaskDetails, TaskOverview } from "./components/TaskDetails";
import { statusLabel, taskMessage } from "./components/taskFormat";

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  task?: AgentTaskResponse;
};
type ApiState = "checking" | "connected" | "unavailable";
type UiError = {
  title: string;
  message: string;
  code: string | null;
  status: number | null;
  requestId: string | null;
  fieldDetails: string[];
};

const apiErrorCopy: Record<string, string> = {
  confirmation_expired: "确认已过期，银行卡没有变更。",
  confirmation_invalidated: "操作内容已变化，请重新发起并核对。",
  confirmation_not_pending: "这项操作已变化，请刷新后查看当前状态。",
  card_version_conflict: "银行卡状态已变化，请刷新后重新操作。",
  idempotency_conflict: "请求与已提交的操作不一致，请重新发起。",
  not_found: "没有找到这项任务，或你无权查看它。",
  task_state_conflict: "任务状态已变化，请查看最新处理进度。",
  tool_input_invalid: "银行卡信息无法识别，请重新描述。",
};

function toUiError(error: unknown): UiError {
  if (error instanceof ApiError) {
    return {
      title: apiErrorCopy[error.code] ?? "请求未完成",
      message: error.message,
      code: error.code,
      status: error.status,
      requestId: error.requestId,
      fieldDetails: error.details.map((item) =>
        item.field ? item.field + "：" + item.message : item.message,
      ),
    };
  }
  const detail = error instanceof Error ? error.message : "未知错误，请重试。";
  const isNetworkError =
    error instanceof TypeError ||
    detail.toLowerCase().includes("fetch") ||
    detail.toLowerCase().includes("network");
  return {
    title: isNetworkError ? "暂时无法连接服务" : "请求未完成",
    message: isNetworkError
      ? "请检查服务连接后重试。"
      : "操作没有完成，请查看错误详情。",
    code: null,
    status: null,
    requestId: null,
    fieldDetails: [detail],
  };
}

function conversationKey(): string {
  const key = "finorch.demo.conversation";
  try {
    const saved = sessionStorage.getItem(key);
    if (saved) return saved;
    const id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
    return id;
  } catch {
    return crypto.randomUUID();
  }
}

function userName(session: DemoSessionResponse | null): string {
  if (!session) return "演示用户";
  return session.display_name === "Demo User One"
    ? "演示用户"
    : session.display_name;
}

function modeLabel(mode: DemoSessionResponse["agent_provider"]): string {
  return mode === "fake" ? "演示模式" : "兼容模型模式";
}

function environmentLabel(
  environment: DemoSessionResponse["environment"],
): string {
  return environment === "development" ? "本地开发" : "测试环境";
}

function initialContextOpen(): boolean {
  return typeof window !== "undefined" && window.innerWidth >= 1100;
}

function ErrorBanner({
  error,
  onRetry,
  onDismiss,
  retrying,
}: {
  error: UiError;
  onRetry: () => void;
  onDismiss: () => void;
  retrying: boolean;
}) {
  return (
    <section aria-live="assertive" className="error-banner" role="alert">
      <span aria-hidden="true" className="error-mark">
        <AppIcon name="info" size={17} />
      </span>
      <div className="error-copy">
        <strong>{error.title}</strong>
        <p>{error.message}</p>
        <details>
          <summary>查看错误详情</summary>
          <div className="error-detail">
            {error.code ? <code>{error.code}</code> : null}
            {error.status ? <span>HTTP {error.status}</span> : null}
            {error.requestId ? <code>请求编号 {error.requestId}</code> : null}
            {error.fieldDetails.map((detail) => (
              <p key={detail}>{detail}</p>
            ))}
          </div>
        </details>
      </div>
      <div className="error-actions">
        <button
          className="button button-secondary"
          disabled={retrying}
          onClick={onRetry}
          type="button"
        >
          {retrying ? "正在重试…" : "重试"}
        </button>
        <button
          aria-label="关闭错误提示"
          className="icon-button error-dismiss"
          onClick={onDismiss}
          type="button"
        >
          <AppIcon name="close" />
        </button>
      </div>
    </section>
  );
}

function EnvironmentDetails({
  mode,
  session,
  apiVersion,
}: {
  mode: DemoSessionResponse["agent_provider"];
  session: DemoSessionResponse | null;
  apiVersion: string | null;
}) {
  return (
    <details className="environment-details">
      <summary>
        <span className={"mode-dot mode-dot-" + mode} />
        {modeLabel(mode)}
        <AppIcon name="chevron-down" size={15} />
      </summary>
      <div className="environment-popover">
        <h2>环境详情</h2>
        <p>
          {mode === "fake"
            ? "当前使用确定性模拟规则，不调用外部模型。"
            : "当前选择兼容模型模式，请求由服务端转发。若服务端未配置模型，任务会明确失败；页面不会读取或显示密钥。"}
        </p>
        <dl>
          <div>
            <dt>数据环境</dt>
            <dd>
              {session ? environmentLabel(session.environment) : "正在读取"}
            </dd>
          </div>
          <div>
            <dt>数据版本</dt>
            <dd>{session?.dataset_version ?? "—"}</dd>
          </div>
          <div>
            <dt>服务版本</dt>
            <dd>{apiVersion ?? "—"}</dd>
          </div>
        </dl>
        <p className="environment-note">
          账户和银行卡均为模拟数据，不连接真实银行或支付服务。
        </p>
      </div>
    </details>
  );
}

function StatusIndicator({ status }: { status: ApiState }) {
  const copy = {
    checking: "连接中",
    connected: "服务已连接",
    unavailable: "服务不可用",
  }[status];
  return (
    <span
      aria-label={copy}
      aria-live="polite"
      className={"connection-status connection-" + status}
      title={copy}
    >
      <span aria-hidden="true" className="connection-dot" />
      {copy}
    </span>
  );
}

function promptSuggestions(cards: CardListResponse["items"]): string[] {
  const suggestions = ["查看我的银行卡"];
  const card = cards[0];
  if (card) suggestions.push("查询尾号 " + card.card_suffix + " 的卡片状态");
  const activeCard = cards.find((item) => item.status === "active");
  if (activeCard)
    suggestions.push("冻结尾号 " + activeCard.card_suffix + " 的卡");
  const frozenCard = cards.find((item) => item.status === "frozen");
  if (frozenCard)
    suggestions.push("解冻尾号 " + frozenCard.card_suffix + " 的卡");
  return suggestions.slice(0, 3);
}

export default function App() {
  const [conversationId] = useState(conversationKey);
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [apiVersion, setApiVersion] = useState<string | null>(null);
  const [session, setSession] = useState<DemoSessionResponse | null>(null);
  const [cards, setCards] = useState<CardListResponse["items"]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [activeTask, setActiveTask] = useState<AgentTaskResponse | null>(null);
  const [auditState, setAuditState] = useState<{
    key: string;
    events: AuditResponse["events"];
    error: ApiError | Error | null;
  } | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [requestError, setRequestError] = useState<UiError | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [activeSection, setActiveSection] = useState<"assistant" | "cards">(
    "assistant",
  );
  const [contextOpen, setContextOpen] = useState(initialContextOpen);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const conversationRef = useRef<HTMLDivElement>(null);
  const activeTaskId = activeTask?.id;
  const activeTaskStatus = activeTask?.status;
  const activeTaskVersion = activeTask?.version;
  const auditKey =
    activeTaskId && activeTaskVersion !== undefined
      ? activeTaskId + ":" + activeTaskVersion
      : null;
  const matchingAudit =
    auditKey && auditState?.key === auditKey ? auditState : null;
  const audit = matchingAudit?.events ?? [];
  const auditLoading = detailsOpen && Boolean(activeTask) && !matchingAudit;
  const auditError = matchingAudit?.error ?? null;

  const applyTask = useCallback((task: AgentTaskResponse) => {
    setActiveTask(task);
    setMessages((current) => {
      const response: Message = {
        id: "task-" + task.id,
        role: "assistant",
        text: taskMessage(task),
        task,
      };
      return [
        ...current.filter((message) => message.task?.id !== task.id),
        response,
      ];
    });
  }, []);

  useEffect(() => {
    let current = true;
    apiClient
      .readHealth()
      .then((health) => {
        if (!current) return;
        setApiState(health.status === "ok" ? "connected" : "unavailable");
        setApiVersion(health.version);
      })
      .catch((error: unknown) => {
        if (!current) return;
        setApiState("unavailable");
        setApiVersion(null);
        setRequestError(toUiError(error));
      });

    Promise.all([apiClient.readSession(), apiClient.readCards()])
      .then(([demo, cardPage]) => {
        if (!current) return;
        setSession(demo);
        setCards(cardPage.items);
      })
      .catch((error: unknown) => {
        if (current) setRequestError(toUiError(error));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, []);

  useEffect(() => {
    const desktopContext = window.matchMedia("(min-width: 1100px)");
    const desktopNavigation = window.matchMedia("(min-width: 960px)");
    const updateLayout = () => {
      setContextOpen(desktopContext.matches);
      if (desktopNavigation.matches) setMobileNavOpen(false);
    };
    desktopContext.addEventListener("change", updateLayout);
    desktopNavigation.addEventListener("change", updateLayout);
    updateLayout();
    return () => {
      desktopContext.removeEventListener("change", updateLayout);
      desktopNavigation.removeEventListener("change", updateLayout);
    };
  }, []);

  useEffect(() => {
    const container = conversationRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messages.length, busy]);

  useEffect(() => {
    if (
      !activeTaskId ||
      !activeTaskStatus ||
      !["pending", "planning", "running"].includes(activeTaskStatus)
    )
      return;
    let current = true;
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      apiClient
        .readTask(activeTaskId)
        .then((task) => {
          if (current) applyTask(task);
        })
        .catch((error: unknown) => {
          if (current) setRequestError(toUiError(error));
        })
        .finally(() => {
          polling = false;
        });
    }, 1500);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [activeTaskId, activeTaskStatus, applyTask]);

  useEffect(() => {
    if (!activeTaskId || !detailsOpen || !auditKey) return;
    let current = true;
    apiClient
      .readAudit(activeTaskId)
      .then((data) => {
        if (current)
          setAuditState({
            key: auditKey,
            events: data.events,
            error: null,
          });
      })
      .catch((error: unknown) => {
        if (!current) return;
        setAuditState({
          key: auditKey,
          events: [],
          error:
            error instanceof Error ? error : new Error("读取操作记录失败。"),
        });
      });
    return () => {
      current = false;
    };
  }, [activeTaskId, activeTaskVersion, detailsOpen, auditKey]);

  async function refreshCards() {
    setRefreshing(true);
    setRequestError(null);
    try {
      setCards((await apiClient.readCards()).items);
    } catch (error) {
      setRequestError(toUiError(error));
    } finally {
      setRefreshing(false);
    }
  }

  async function retryConnection() {
    setRetrying(true);
    setApiState("checking");
    setRequestError(null);
    try {
      const [health, demo, cardPage] = await Promise.all([
        apiClient.readHealth(),
        apiClient.readSession(),
        apiClient.readCards(),
      ]);
      setApiState(health.status === "ok" ? "connected" : "unavailable");
      setApiVersion(health.version);
      setSession(demo);
      setCards(cardPage.items);
    } catch (error) {
      setApiState("unavailable");
      setRequestError(toUiError(error));
    } finally {
      setRetrying(false);
      setLoading(false);
    }
  }

  async function sendMessage(value = draft) {
    const requestText = value.trim();
    if (!requestText || busy || !session) return;
    setDraft("");
    setBusy(true);
    setRequestError(null);
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", text: requestText },
    ]);
    try {
      const task =
        activeTask &&
        ["awaiting_input", "awaiting_confirmation"].includes(activeTask.status)
          ? await apiClient.provideTaskInput(activeTask.id, {
              request_text: requestText,
            })
          : await apiClient.createTask({
              request_text: requestText,
              conversation_id: conversationId,
            });
      applyTask(task);
      if (task.status === "completed") await refreshCards();
    } catch (error) {
      setRequestError(toUiError(error));
    } finally {
      setBusy(false);
    }
  }

  async function confirmTask(task: AgentTaskResponse) {
    if (!task.confirmation || busy) return;
    setBusy(true);
    setRequestError(null);
    try {
      applyTask(await apiClient.confirmTask(task));
      await refreshCards();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          applyTask(await apiClient.readTask(task.id));
          await refreshCards();
        } catch (refreshError) {
          setRequestError(toUiError(refreshError));
        }
      } else {
        setRequestError(toUiError(error));
      }
    } finally {
      setBusy(false);
    }
  }

  async function cancelTask(task: AgentTaskResponse) {
    if (busy) return;
    setBusy(true);
    setRequestError(null);
    try {
      applyTask(await apiClient.cancelTask(task.id));
      await refreshCards();
    } catch (error) {
      setRequestError(toUiError(error));
    } finally {
      setBusy(false);
    }
  }

  function showTaskDetails() {
    setDetailsOpen(true);
    setContextOpen(true);
    setMobileNavOpen(false);
    window.requestAnimationFrame(() => {
      document.getElementById("task-details")?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    });
  }

  const mode = activeTask?.provider_mode ?? session?.agent_provider ?? "fake";

  return (
    <div className="app-shell">
      <Navigation
        activeSection={activeSection}
        hasTask={Boolean(activeTask)}
        mobileOpen={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
        onSelect={(section) => {
          setActiveSection(section);
          if (section === "cards") setContextOpen(true);
        }}
        onShowDetails={showTaskDetails}
      />

      <div className="app-main">
        <header className="topbar">
          <div className="topbar-inner">
            <div className="topbar-left">
              <button
                aria-controls="main-navigation"
                aria-expanded={mobileNavOpen}
                aria-label={mobileNavOpen ? "关闭导航菜单" : "打开导航菜单"}
                className="icon-button mobile-menu-button"
                onClick={() => setMobileNavOpen((open) => !open)}
                type="button"
              >
                <AppIcon name={mobileNavOpen ? "close" : "menu"} size={20} />
              </button>
            </div>
            <div className="topbar-actions">
              <span className="account-name">{userName(session)}</span>
              <EnvironmentDetails
                apiVersion={apiVersion}
                mode={mode}
                session={session}
              />
              <StatusIndicator status={apiState} />
            </div>
          </div>
        </header>

        <main className="page-content">
          <div className="workspace-heading">
            <h1>智能助手</h1>
          </div>

          {requestError ? (
            <ErrorBanner
              error={requestError}
              onDismiss={() => setRequestError(null)}
              onRetry={() => void retryConnection()}
              retrying={retrying}
            />
          ) : null}

          <div className="workbench-grid">
            <section
              aria-labelledby="assistant-title"
              className="assistant-panel"
              id="assistant"
            >
              <div className="assistant-header">
                <div>
                  <h2 id="assistant-title">对话</h2>
                  <p>银行卡服务</p>
                </div>
              </div>

              <div
                aria-live="polite"
                className="conversation"
                ref={conversationRef}
                role="log"
              >
                {messages.length === 0 ? (
                  <div className="welcome-state">
                    <span aria-hidden="true" className="welcome-mark">
                      F
                    </span>
                    <h3>你好，{userName(session)}</h3>
                    <p>
                      {loading
                        ? "正在读取演示账户…"
                        : "我可以帮你查询银行卡，也可以在你确认后冻结或解冻卡片。"}
                    </p>
                    {!loading ? (
                      <div className="suggestion-group">
                        <span className="suggestion-label">你可以试试</span>
                        <div className="suggestions">
                          {promptSuggestions(cards).map((prompt) => (
                            <button
                              className="suggestion-button"
                              disabled={busy || !session}
                              key={prompt}
                              onClick={() => void sendMessage(prompt)}
                              type="button"
                            >
                              {prompt}
                              <AppIcon name="arrow-right" size={16} />
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="message-list">
                    {messages.map((message) => (
                      <article
                        className={"message message-" + message.role}
                        key={message.id}
                      >
                        <div className="message-author">
                          {message.role === "user"
                            ? userName(session)
                            : "FinOrch"}
                        </div>
                        <div
                          className={
                            "message-bubble message-bubble-" + message.role
                          }
                        >
                          <p>{message.text}</p>
                        </div>
                        {message.task ? (
                          <>
                            <div className="message-status">
                              <span
                                className={
                                  "task-status task-status-" +
                                  message.task.status
                                }
                              >
                                {statusLabel(message.task.status)}
                              </span>
                            </div>
                            {message.task.confirmation ? (
                              <ConfirmationCard
                                busy={busy}
                                confirmation={message.task.confirmation}
                                onCancel={() => void cancelTask(message.task!)}
                                onConfirm={() =>
                                  void confirmTask(message.task!)
                                }
                              />
                            ) : null}
                          </>
                        ) : null}
                      </article>
                    ))}
                  </div>
                )}
                {busy ? (
                  <p className="processing-indicator" role="status">
                    <span aria-hidden="true" className="processing-dot" />
                    正在处理…
                  </p>
                ) : null}
              </div>

              <form
                className="composer"
                onSubmit={(event) => {
                  event.preventDefault();
                  void sendMessage();
                }}
              >
                {activeTask?.status === "awaiting_input" ? (
                  <p className="composer-hint">补充信息将继续当前任务。</p>
                ) : activeTask?.status === "awaiting_confirmation" ? (
                  <p className="composer-hint">
                    修改请求会取消当前确认，并重新核对操作内容。
                  </p>
                ) : null}
                <label className="visually-hidden" htmlFor="agent-request">
                  输入银行卡请求
                </label>
                <div className="composer-row">
                  <textarea
                    id="agent-request"
                    maxLength={1000}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (
                        event.key === "Enter" &&
                        !event.shiftKey &&
                        !event.nativeEvent.isComposing
                      ) {
                        event.preventDefault();
                        void sendMessage();
                      }
                    }}
                    placeholder="例如：冻结尾号 1042 的卡"
                    rows={2}
                    value={draft}
                  />
                  <button
                    aria-label="发送请求"
                    className="send-button"
                    disabled={busy || !draft.trim() || !session}
                    type="submit"
                  >
                    <AppIcon name="send" size={19} />
                  </button>
                </div>
                <div className="composer-foot">
                  <span>Enter 发送，Shift + Enter 换行</span>
                  <span>只处理演示银行卡</span>
                </div>
              </form>
            </section>

            <details
              className="context-disclosure"
              onToggle={(event) => setContextOpen(event.currentTarget.open)}
              open={contextOpen}
            >
              <summary className="context-summary">
                <span className="context-summary-icon">
                  <AppIcon name="overview" size={19} />
                </span>
                <span className="context-summary-copy">
                  <strong>账户信息</strong>
                  <small>银行卡与处理进度</small>
                </span>
                <AppIcon
                  className="context-chevron"
                  name="chevron-down"
                  size={18}
                />
              </summary>
              <div className="context-content">
                <CardList
                  cards={cards}
                  loading={loading}
                  onRefresh={() => void refreshCards()}
                  refreshing={refreshing}
                />
                <TaskOverview
                  busy={busy}
                  onCancel={() => {
                    if (activeTask) void cancelTask(activeTask);
                  }}
                  task={activeTask}
                />
                <TaskDetails
                  audit={audit}
                  auditError={auditError}
                  auditLoading={auditLoading}
                  onOpenChange={setDetailsOpen}
                  open={detailsOpen}
                  task={activeTask}
                />
              </div>
            </details>
          </div>
        </main>
      </div>
    </div>
  );
}
