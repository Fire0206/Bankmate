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
import { Navigation, type Section } from "./components/Navigation";
import { TaskResult } from "./components/TaskResult";
import { TaskDetails } from "./components/TaskDetails";
import {
  hasSuccessfulChange,
  taskMessage,
  taskStatusLabel,
} from "./components/taskFormat";

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  task?: AgentTaskResponse;
  taskId?: string;
  restored?: boolean;
};
type ApiState = "checking" | "connected" | "unavailable";
type RecoveryAction = "connection" | "task" | "write-lookup" | "write-retry";
type ComposerChoice = { taskId: string; mode: "new" | "continue" };
type UiError = {
  title: string;
  message: string;
  code: string | null;
  status: number | null;
  requestId: string | null;
  fieldDetails: string[];
};
type PendingWrite =
  | {
      kind: "create";
      key: string;
      conversationId: string;
      requestText: string;
    }
  | {
      kind: "input";
      key: string;
      conversationId: string;
      taskId: string;
      requestText: string;
    }
  | {
      kind: "confirm";
      key: string;
      conversationId: string;
      taskId: string;
      challengeId: string;
      parametersHash: string;
    }
  | {
      kind: "cancel";
      key: string;
      conversationId: string;
      taskId: string;
    };

const pendingWriteStorageKey = "finorch.demo.pending-write";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readPendingWrite(): PendingWrite | null {
  try {
    const parsed: unknown = JSON.parse(
      sessionStorage.getItem(pendingWriteStorageKey) ?? "null",
    );
    if (!isRecord(parsed)) return null;
    const {
      kind,
      key,
      conversationId,
      taskId,
      requestText,
      challengeId,
      parametersHash,
    } = parsed;
    if (
      typeof key !== "string" ||
      typeof conversationId !== "string" ||
      typeof kind !== "string"
    )
      return null;
    if (kind === "create" && typeof requestText === "string")
      return { kind, key, conversationId, requestText };
    if (
      kind === "input" &&
      typeof taskId === "string" &&
      typeof requestText === "string"
    )
      return { kind, key, conversationId, taskId, requestText };
    if (
      kind === "confirm" &&
      typeof taskId === "string" &&
      typeof challengeId === "string" &&
      typeof parametersHash === "string"
    )
      return { kind, key, conversationId, taskId, challengeId, parametersHash };
    if (kind === "cancel" && typeof taskId === "string")
      return { kind, key, conversationId, taskId };
    return null;
  } catch {
    return null;
  }
}

function isNetworkFailure(error: unknown): boolean {
  if (error instanceof TypeError) return true;
  const message = error instanceof Error ? error.message.toLowerCase() : "";
  return message.includes("fetch") || message.includes("network");
}

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
      message:
        apiErrorCopy[error.code] ??
        "请求没有完成。请刷新任务状态，再根据实际结果继续。",
      code: error.code,
      status: error.status,
      requestId: error.requestId,
      fieldDetails: error.details.map((item) =>
        item.field ? item.field + "：" + item.message : item.message,
      ),
    };
  }
  const detail = error instanceof Error ? error.message : "未知错误，请重试。";
  const isNetworkError = isNetworkFailure(error);
  return {
    title: isNetworkError ? "暂时无法连接服务" : "请求未完成",
    message: isNetworkError
      ? "请恢复连接后先查询这次请求的处理状态。"
      : "请求没有完成。请刷新任务状态，再根据实际结果继续。",
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

function environmentLabel(
  environment: DemoSessionResponse["environment"],
): string {
  return environment === "development" ? "本地开发" : "测试环境";
}

function initialSection(): Section {
  return typeof window !== "undefined" && window.location.hash === "#cards"
    ? "cards"
    : "assistant";
}

function ErrorBanner({
  error,
  onRetry,
  retryLabel,
  retryAction,
  onSecondary,
  secondaryLabel,
  secondaryAction,
  onTertiary,
  tertiaryLabel,
  tertiaryAction,
  onDismiss,
  busyAction,
}: {
  error: UiError;
  onRetry: () => void;
  retryLabel: string;
  retryAction: RecoveryAction;
  onSecondary?: () => void;
  secondaryLabel?: string;
  secondaryAction?: RecoveryAction;
  onTertiary?: () => void;
  tertiaryLabel?: string;
  tertiaryAction?: RecoveryAction;
  onDismiss: () => void;
  busyAction: RecoveryAction | null;
}) {
  const actionLabel: Record<RecoveryAction, string> = {
    connection: "正在连接…",
    task: "正在读取…",
    "write-lookup": "正在查询…",
    "write-retry": "正在重试…",
  };
  const busy = busyAction !== null;
  return (
    <section aria-live="assertive" className="error-banner" role="alert">
      <span aria-hidden="true" className="error-mark">
        <AppIcon name="info" size={17} />
      </span>
      <div className="error-copy">
        <strong>{error.title}</strong>
        <p>{error.message}</p>
        {import.meta.env.DEV ? (
          <details className="developer-diagnostics">
            <summary>本地开发诊断</summary>
            <div className="error-detail">
              {error.code ? <code>{error.code}</code> : null}
              {error.status ? <span>HTTP {error.status}</span> : null}
              {error.requestId ? <code>请求编号 {error.requestId}</code> : null}
              {error.fieldDetails.map((detail) => (
                <p key={detail}>{detail}</p>
              ))}
            </div>
          </details>
        ) : null}
      </div>
      <div className="error-actions">
        <button
          className="button button-secondary"
          disabled={busy}
          onClick={onRetry}
          type="button"
        >
          {busyAction === retryAction ? actionLabel[retryAction] : retryLabel}
        </button>
        {onSecondary && secondaryLabel ? (
          <button
            className="text-button"
            disabled={busy}
            onClick={onSecondary}
            type="button"
          >
            {busyAction === secondaryAction && secondaryAction
              ? actionLabel[secondaryAction]
              : secondaryLabel}
          </button>
        ) : null}
        {onTertiary && tertiaryLabel ? (
          <button
            className="text-button"
            disabled={busy}
            onClick={onTertiary}
            type="button"
          >
            {busyAction === tertiaryAction && tertiaryAction
              ? actionLabel[tertiaryAction]
              : tertiaryLabel}
          </button>
        ) : null}
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
  if (!import.meta.env.DEV) return null;
  return (
    <details className="environment-details developer-diagnostics">
      <summary>
        演示说明
        <AppIcon name="chevron-down" size={15} />
      </summary>
      <div className="environment-popover">
        <h2>本地运行信息</h2>
        <p>
          {mode === "fake"
            ? "当前使用 Fake Provider 的确定性模拟规则，没有调用外部模型。"
            : "当前使用 OpenAI-compatible Provider，由服务端转发模型请求。页面不会读取或显示密钥。"}
        </p>
        <dl>
          <div>
            <dt>Provider</dt>
            <dd>{mode === "fake" ? "Fake Provider" : "OpenAI-compatible"}</dd>
          </div>
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
          银行卡、账单和订阅均为模拟数据，不连接真实银行或支付服务。
        </p>
      </div>
    </details>
  );
}

function StatusIndicator({ status }: { status: ApiState }) {
  if (status === "connected") return null;
  const copy = {
    checking: "连接中",
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

function promptSuggestions(): string[] {
  return [
    "我这个月花了多少钱",
    "我有哪些自动扣费",
    "查看适合我的理财产品",
    "我要转账",
  ];
}

function canContinueTask(task: AgentTaskResponse | null): boolean {
  if (!task) return false;
  return (
    task.status === "awaiting_input" ||
    task.status === "awaiting_confirmation" ||
    (task.status === "failed" && hasSuccessfulChange(task))
  );
}

export default function App() {
  const [conversationId] = useState(conversationKey);
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [apiVersion, setApiVersion] = useState<string | null>(null);
  const [session, setSession] = useState<DemoSessionResponse | null>(null);
  const [cards, setCards] = useState<CardListResponse["items"]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [activeTask, setActiveTask] = useState<AgentTaskResponse | null>(null);
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(
    readPendingWrite,
  );
  const [auditState, setAuditState] = useState<{
    key: string;
    events: AuditResponse["events"];
    error: ApiError | Error | null;
  } | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshingTask, setRefreshingTask] = useState(false);
  const [recoveryAction, setRecoveryAction] = useState<RecoveryAction | null>(
    null,
  );
  const [requestError, setRequestError] = useState<UiError | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [activeSection, setActiveSection] = useState<Section>(initialSection);
  const [detailsTaskId, setDetailsTaskId] = useState<string | null>(null);
  const [composerChoice, setComposerChoice] = useState<ComposerChoice | null>(
    null,
  );
  const conversationRef = useRef<HTMLDivElement>(null);
  const activeTaskId = activeTask?.id;
  const activeTaskStatus = activeTask?.status;
  const activeTaskVersion = activeTask?.version;
  const detailsOpen = detailsTaskId === activeTaskId;
  const auditKey =
    activeTaskId && activeTaskVersion !== undefined
      ? activeTaskId + ":" + activeTaskVersion
      : null;
  const matchingAudit =
    auditKey && auditState?.key === auditKey ? auditState : null;
  const audit = matchingAudit?.events ?? [];
  const auditLoading = detailsOpen && Boolean(activeTask) && !matchingAudit;
  const auditError = matchingAudit?.error ?? null;
  const needsTaskChoice = canContinueTask(activeTask);
  const selectedChoice =
    composerChoice?.taskId === activeTaskId
      ? (composerChoice?.mode ?? null)
      : null;
  const recentTerminalTask =
    messages.length === 1 &&
    messages[0]?.restored &&
    messages[0].task &&
    messages[0].task.status === "completed"
      ? messages[0].task
      : null;
  const showWelcome = messages.length === 0 || Boolean(recentTerminalTask);

  const applyTask = useCallback((task: AgentTaskResponse, restored = false) => {
    setActiveTask(task);
    setMessages((current) => {
      const existingIndex = current.findIndex(
        (message) => message.task?.id === task.id,
      );
      const existingMessage =
        existingIndex >= 0 ? current[existingIndex] : null;
      const previousMessages = current.map((message) => {
        if (message.role !== "user" || message.taskId === task.id)
          return message;
        if (message.taskId || message.text !== task.request_text)
          return message;
        return { ...message, taskId: task.id };
      });
      const previousRestored = Boolean(existingMessage?.restored || restored);
      const updatedMessages = previousMessages.filter(
        (message) => message.task?.id !== task.id,
      );
      let lastRelatedUser = -1;
      updatedMessages.forEach((message, index) => {
        if (message.role === "user" && message.taskId === task.id)
          lastRelatedUser = index;
      });
      const insertionIndex =
        lastRelatedUser >= 0
          ? lastRelatedUser + 1
          : existingIndex >= 0
            ? Math.min(existingIndex, updatedMessages.length)
            : updatedMessages.length;
      updatedMessages.splice(insertionIndex, 0, {
        id: "task-" + task.id,
        role: "assistant",
        text: taskMessage(task),
        task,
        restored: previousRestored,
      });
      return updatedMessages;
    });
  }, []);

  const storePendingWrite = useCallback((write: PendingWrite | null) => {
    setPendingWrite(write);
    try {
      if (write)
        sessionStorage.setItem(pendingWriteStorageKey, JSON.stringify(write));
      else sessionStorage.removeItem(pendingWriteStorageKey);
    } catch {
      // Session storage is a recovery aid, never an identity or authorization source.
    }
  }, []);

  const lookupPendingWrite = useCallback(async (write: PendingWrite) => {
    const task = await apiClient.readTaskByIdempotencyKey(
      write.key,
      write.conversationId,
      write.kind,
      write.kind === "create" ? undefined : write.taskId,
    );
    if (task) {
      const resolved =
        write.kind !== "confirm" ||
        task.status !== "awaiting_confirmation" ||
        task.confirmation?.id !== write.challengeId;
      return { task, resolved };
    }
    if (write.kind !== "create") {
      return { task: await apiClient.readTask(write.taskId), resolved: false };
    }
    return { task: null, resolved: false };
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
      .then(async ([demo, cardPage]) => {
        if (!current) return;
        setSession(demo);
        setCards(cardPage.items);
        const savedWrite = readPendingWrite();
        try {
          if (savedWrite) {
            const recovered = await lookupPendingWrite(savedWrite);
            if (!current) return;
            if (recovered.task) applyTask(recovered.task, true);
            if (recovered.resolved) {
              storePendingWrite(null);
            } else {
              setRequestError({
                title: "提交状态尚未确认",
                message: recovered.task
                  ? "已读取服务端任务。请确认当前状态，或使用相同请求安全重试。"
                  : "暂未找到这次提交的任务记录。请先查询结果，再使用原请求安全重试。",
                code: null,
                status: null,
                requestId: null,
                fieldDetails: [],
              });
            }
          } else {
            const recent = await apiClient.readRecentTask(conversationId);
            if (current && recent) applyTask(recent, true);
          }
        } catch (error) {
          if (current) setRequestError(toUiError(error));
        }
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
  }, [applyTask, conversationId, lookupPendingWrite, storePendingWrite]);

  useEffect(() => {
    const desktopNavigation = window.matchMedia("(min-width: 960px)");
    const updateLayout = () => {
      if (desktopNavigation.matches) setMobileNavOpen(false);
    };
    desktopNavigation.addEventListener("change", updateLayout);
    updateLayout();
    return () => {
      desktopNavigation.removeEventListener("change", updateLayout);
    };
  }, []);

  useEffect(() => {
    const syncSection = () => {
      setActiveSection(
        window.location.hash === "#cards" ? "cards" : "assistant",
      );
    };
    window.addEventListener("hashchange", syncSection);
    return () => window.removeEventListener("hashchange", syncSection);
  }, []);

  useEffect(() => {
    const nextHash = activeSection === "cards" ? "#cards" : "#assistant";
    if (window.location.hash !== nextHash)
      window.history.replaceState(null, "", nextHash);
  }, [activeSection]);

  useEffect(() => {
    if (messages.length > 0 && conversationRef.current)
      conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
  }, [messages.length]);

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
    setRecoveryAction("connection");
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
      setRecoveryAction(null);
      setLoading(false);
    }
  }

  async function executeWrite(write: PendingWrite): Promise<AgentTaskResponse> {
    if (write.kind === "create") {
      return apiClient.createTask(
        {
          request_text: write.requestText,
          conversation_id: write.conversationId,
        },
        write.key,
      );
    }
    if (write.kind === "input") {
      return apiClient.provideTaskInput(
        write.taskId,
        { request_text: write.requestText },
        write.key,
      );
    }
    if (write.kind === "confirm") {
      return apiClient.confirmTask(
        write.taskId,
        write.challengeId,
        write.parametersHash,
        write.key,
      );
    }
    return apiClient.cancelTask(write.taskId, write.key);
  }

  async function submitWrite(
    write: PendingWrite,
  ): Promise<AgentTaskResponse | null> {
    storePendingWrite(write);
    setBusy(true);
    setRequestError(null);
    try {
      const task = await executeWrite(write);
      applyTask(task);
      storePendingWrite(null);
      if (
        task.status === "completed" ||
        (write.kind === "confirm" &&
          task.steps.some(
            (step) =>
              step.tool_name?.startsWith("card.") &&
              step.status === "succeeded",
          ))
      )
        await refreshCards();
      return task;
    } catch (error) {
      try {
        const recovered = await lookupPendingWrite(write);
        if (recovered.task) applyTask(recovered.task);
        if (recovered.resolved) {
          storePendingWrite(null);
          if (
            recovered.task?.status === "completed" ||
            (write.kind === "confirm" &&
              recovered.task?.steps.some(
                (step) =>
                  step.tool_name?.startsWith("card.") &&
                  step.status === "succeeded",
              ))
          )
            await refreshCards();
          return recovered.task;
        }
      } catch {
        // Keep the idempotency record so the user can query or safely retry it later.
      }
      setRequestError(toUiError(error));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function recoverPendingWrite(allowResubmit: boolean) {
    if (!pendingWrite || recoveryAction || busy) return;
    setRecoveryAction(allowResubmit ? "write-retry" : "write-lookup");
    setBusy(true);
    setRequestError(null);
    try {
      const recovered = await lookupPendingWrite(pendingWrite);
      if (recovered.task) applyTask(recovered.task);
      if (recovered.resolved) {
        storePendingWrite(null);
        if (recovered.task?.status === "completed") await refreshCards();
        return;
      }
      if (!allowResubmit) {
        setRequestError({
          title: "尚未找到已完成的提交",
          message: recovered.task
            ? "服务端任务仍处于当前状态。可以继续查看任务，或用相同幂等键安全重试。"
            : "服务端暂时没有这次请求的记录。若要继续，请用原请求和同一幂等键重试。",
          code: null,
          status: null,
          requestId: null,
          fieldDetails: [],
        });
        return;
      }
      const task = await executeWrite(pendingWrite);
      applyTask(task);
      storePendingWrite(null);
      if (task.status === "completed") await refreshCards();
    } catch (error) {
      try {
        const latest = await lookupPendingWrite(pendingWrite);
        if (latest.task) applyTask(latest.task);
        if (latest.resolved) {
          storePendingWrite(null);
          if (latest.task?.status === "completed") await refreshCards();
          return;
        }
      } catch {
        // Preserve the same request and key while connectivity is uncertain.
      }
      setRequestError(toUiError(error));
    } finally {
      setBusy(false);
      setRecoveryAction(null);
    }
  }

  async function refreshRecentTask() {
    if (recoveryAction || busy) return;
    setRecoveryAction("task");
    setRequestError(null);
    try {
      const task = await apiClient.readRecentTask(conversationId);
      if (task) applyTask(task, true);
    } catch (error) {
      setRequestError(toUiError(error));
    } finally {
      setRecoveryAction(null);
    }
  }

  async function refreshTask() {
    if (!activeTask || refreshingTask) return;
    setRefreshingTask(true);
    try {
      const task = await apiClient.readTask(activeTask.id);
      applyTask(task);
      if (task.status === "completed") await refreshCards();
      setRequestError(null);
    } catch (error) {
      setRequestError(toUiError(error));
    } finally {
      setRefreshingTask(false);
    }
  }

  async function sendMessage(value = draft) {
    const requestText = value.trim();
    if (!requestText || busy || !session || pendingWrite) return;
    if (needsTaskChoice && !selectedChoice) return;
    setDraft("");
    const continuesTask = needsTaskChoice && selectedChoice === "continue";
    setMessages((current) => [
      ...(continuesTask
        ? current
        : current.filter(
            (message) =>
              !(
                message.restored &&
                message.task &&
                ["completed", "failed", "cancelled"].includes(
                  message.task.status,
                )
              ),
          )),
      {
        id: crypto.randomUUID(),
        role: "user",
        text: requestText,
        ...(continuesTask && activeTask ? { taskId: activeTask.id } : {}),
      },
    ]);
    const key = crypto.randomUUID();
    const write: PendingWrite =
      activeTask && continuesTask
        ? {
            kind: "input",
            key,
            conversationId,
            taskId: activeTask.id,
            requestText,
          }
        : { kind: "create", key, conversationId, requestText };
    await submitWrite(write);
  }

  async function startNewTask() {
    if (!activeTask || busy || pendingWrite) return;
    if (
      ["awaiting_input", "awaiting_confirmation"].includes(activeTask.status)
    ) {
      const cancelled = await submitWrite({
        kind: "cancel",
        key: crypto.randomUUID(),
        conversationId: activeTask.conversation_id,
        taskId: activeTask.id,
      });
      if (!cancelled || cancelled.status !== "cancelled") return;
    }
    setComposerChoice({ taskId: activeTask.id, mode: "new" });
    document.getElementById("agent-request")?.focus();
  }

  async function confirmTask(task: AgentTaskResponse) {
    if (!task.confirmation || busy) return;
    await submitWrite({
      kind: "confirm",
      key: task.confirmation.idempotency_key,
      conversationId: task.conversation_id,
      taskId: task.id,
      challengeId: task.confirmation.id,
      parametersHash: task.confirmation.parameters_hash,
    });
  }

  async function cancelTask(task: AgentTaskResponse) {
    if (busy || pendingWrite) return;
    await submitWrite({
      kind: "cancel",
      key: crypto.randomUUID(),
      conversationId: task.conversation_id,
      taskId: task.id,
    });
  }

  function fillPrompt(prompt: string) {
    setActiveSection("assistant");
    setDraft(prompt);
    setMobileNavOpen(false);
    window.requestAnimationFrame(() => {
      document.getElementById("agent-request")?.focus();
    });
  }

  const mode = activeTask?.provider_mode ?? session?.agent_provider ?? "fake";

  return (
    <div className="app-shell">
      <Navigation
        activeSection={activeSection}
        mobileOpen={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
        onSelect={setActiveSection}
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
              <h1 className="topbar-section-name">
                {activeSection === "cards" ? "银行卡" : "智能助手"}
              </h1>
            </div>
            <div className="topbar-actions">
              <span className="account-name">{userName(session)}</span>
              <span
                className="demo-badge"
                title="银行卡、账单和资金数据均为合成数据，不连接真实银行或支付网络"
              >
                模拟数据
              </span>
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
          {requestError ? (
            <ErrorBanner
              error={requestError}
              onDismiss={() => setRequestError(null)}
              onRetry={() =>
                void (pendingWrite
                  ? recoverPendingWrite(false)
                  : retryConnection())
              }
              retryLabel={pendingWrite ? "查询提交结果" : "恢复连接"}
              retryAction={pendingWrite ? "write-lookup" : "connection"}
              onSecondary={
                pendingWrite
                  ? () => void recoverPendingWrite(true)
                  : !activeTask
                    ? () => void refreshRecentTask()
                    : undefined
              }
              secondaryLabel={
                pendingWrite
                  ? "使用相同请求安全重试"
                  : !activeTask
                    ? "重新读取任务状态"
                    : undefined
              }
              secondaryAction={
                pendingWrite ? "write-retry" : !activeTask ? "task" : undefined
              }
              onTertiary={
                pendingWrite ? () => void retryConnection() : undefined
              }
              tertiaryLabel={pendingWrite ? "恢复连接" : undefined}
              tertiaryAction={pendingWrite ? "connection" : undefined}
              busyAction={recoveryAction}
            />
          ) : null}

          {activeSection === "cards" ? (
            <div className="cards-page">
              <CardList
                cards={cards}
                loading={loading}
                onAskAboutCard={fillPrompt}
                onRefresh={() => void refreshCards()}
                refreshing={refreshing}
              />
            </div>
          ) : (
            <section
              aria-label="智能助手对话"
              className={
                "assistant-panel" + (showWelcome ? " assistant-panel-idle" : "")
              }
              id="assistant"
            >
              <div
                aria-live="polite"
                className="conversation"
                ref={conversationRef}
                role="log"
              >
                {showWelcome ? (
                  <div className="welcome-state">
                    <h2>有什么可以帮你？</h2>
                    <p>查询资金情况，或发起需要你确认的模拟操作。</p>
                    {!loading ? (
                      <div className="suggestion-group">
                        <div className="suggestions">
                          {promptSuggestions().map((prompt) => (
                            <button
                              className="suggestion-button"
                              disabled={
                                busy || Boolean(pendingWrite) || !session
                              }
                              key={prompt}
                              onClick={() => fillPrompt(prompt)}
                              type="button"
                            >
                              {prompt}
                            </button>
                          ))}
                        </div>
                        {recentTerminalTask ? (
                          <div className="recent-task">
                            <TaskResult
                              compact
                              compactPrefix="最近完成："
                              task={recentTerminalTask}
                            />
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <p className="welcome-loading" role="status">
                        正在读取演示账户…
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="message-list">
                    {messages.map((message) => {
                      const task = message.task;
                      const isCurrentTask = task?.id === activeTask?.id;
                      if (message.role === "user") {
                        return (
                          <article
                            className="message message-user"
                            key={message.id}
                          >
                            <div className="message-bubble message-bubble-user">
                              <p>{message.text}</p>
                            </div>
                          </article>
                        );
                      }
                      if (!task) {
                        return (
                          <article
                            className="message message-assistant"
                            key={message.id}
                          >
                            <p className="task-message">{message.text}</p>
                          </article>
                        );
                      }
                      return (
                        <article
                          className="message message-assistant"
                          key={message.id}
                        >
                          {message.restored ? (
                            <div className="restored-task">
                              <span>已恢复最近任务</span>
                              <blockquote>{task.request_text}</blockquote>
                            </div>
                          ) : null}
                          {message.text &&
                          ["awaiting_input", "failed", "cancelled"].includes(
                            task.status,
                          ) ? (
                            <p
                              className={
                                "task-message" +
                                (task.status === "failed"
                                  ? " task-message-error"
                                  : "")
                              }
                            >
                              {message.text}
                            </p>
                          ) : null}
                          {isCurrentTask && task.status === "completed" ? (
                            <TaskResult task={task} />
                          ) : null}
                          {isCurrentTask &&
                          (task.status !== "completed" ||
                            hasSuccessfulChange(task)) ? (
                            <TaskDetails
                              audit={audit}
                              auditError={auditError}
                              auditLoading={auditLoading}
                              busy={busy}
                              onCancel={() => void cancelTask(task)}
                              onOpenChange={(open) =>
                                setDetailsTaskId(open ? task.id : null)
                              }
                              onRefresh={() => void refreshTask()}
                              open={detailsOpen}
                              refreshing={refreshingTask}
                              task={task}
                            />
                          ) : task.status !== "completed" ? (
                            <span
                              className={
                                "task-status task-status-" +
                                (task.status === "failed" &&
                                hasSuccessfulChange(task)
                                  ? "partial"
                                  : task.status)
                              }
                            >
                              {taskStatusLabel(task)}
                            </span>
                          ) : null}
                          {task.confirmation ? (
                            <ConfirmationCard
                              busy={busy}
                              confirmation={task.confirmation}
                              hasPreviousChanges={hasSuccessfulChange(task)}
                              onCancel={() => void cancelTask(task)}
                              onConfirm={() => void confirmTask(task)}
                            />
                          ) : null}
                          {task.status !== "completed" || !isCurrentTask ? (
                            <TaskResult compact={!isCurrentTask} task={task} />
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                )}
                {busy && !activeTask ? (
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
                {needsTaskChoice && !pendingWrite ? (
                  <div
                    className="composer-choice"
                    role="group"
                    aria-label="任务输入方式"
                  >
                    <span>
                      {activeTask?.status === "awaiting_confirmation"
                        ? "当前有待确认操作"
                        : activeTask?.status === "awaiting_input"
                          ? "当前任务需要补充信息"
                          : "当前任务部分完成"}
                    </span>
                    <div>
                      <button
                        className={
                          selectedChoice === "continue" ? "choice-active" : ""
                        }
                        disabled={busy}
                        onClick={() =>
                          activeTask &&
                          setComposerChoice({
                            taskId: activeTask.id,
                            mode: "continue",
                          })
                        }
                        type="button"
                      >
                        补充当前任务
                      </button>
                      <button
                        className={
                          selectedChoice === "new" ? "choice-active" : ""
                        }
                        disabled={busy}
                        onClick={() => void startNewTask()}
                        type="button"
                      >
                        开始新任务
                      </button>
                    </div>
                  </div>
                ) : null}
                {pendingWrite ? (
                  <p className="composer-hint">
                    提交结果尚未确认。请先查询这次请求的状态，不要重新发起。
                  </p>
                ) : needsTaskChoice &&
                  selectedChoice === "continue" &&
                  activeTask?.status === "awaiting_confirmation" ? (
                  <p className="composer-hint">
                    补充当前任务会使这次确认失效，操作内容需要重新核对。
                  </p>
                ) : needsTaskChoice &&
                  !selectedChoice &&
                  activeTask?.status === "awaiting_confirmation" ? (
                  <p className="composer-hint">
                    开始新任务会取消待确认操作；已执行的操作不会撤销。
                  </p>
                ) : needsTaskChoice &&
                  !selectedChoice &&
                  activeTask?.status === "awaiting_input" ? (
                  <p className="composer-hint">
                    开始新任务会结束当前请求；已执行的操作不会撤销。
                  </p>
                ) : needsTaskChoice &&
                  !selectedChoice &&
                  activeTask?.status === "failed" ? (
                  <p className="composer-hint">
                    已执行的操作不会因切换任务而撤销。
                  </p>
                ) : null}
                {!needsTaskChoice || selectedChoice ? (
                  <>
                    <label className="visually-hidden" htmlFor="agent-request">
                      输入请求
                    </label>
                    <div className="composer-row">
                      <textarea
                        id="agent-request"
                        disabled={
                          Boolean(pendingWrite) ||
                          (needsTaskChoice && !selectedChoice)
                        }
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
                        placeholder={
                          needsTaskChoice && !selectedChoice
                            ? "先选择补充当前任务或开始新任务"
                            : selectedChoice === "continue"
                              ? "补充这项任务所需的信息"
                              : "输入你需要查询或办理的事项"
                        }
                        rows={1}
                        value={draft}
                      />
                      <button
                        aria-label="发送请求"
                        className="send-button"
                        disabled={
                          busy ||
                          Boolean(pendingWrite) ||
                          !draft.trim() ||
                          !session ||
                          (needsTaskChoice && !selectedChoice)
                        }
                        type="submit"
                      >
                        <AppIcon name="send" size={19} />
                      </button>
                    </div>
                  </>
                ) : null}
              </form>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
