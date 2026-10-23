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
import { ConfirmationModal } from "./components/ConfirmationModal";
import { DemoGate } from "./components/DemoGate";
import { FocusedOverview } from "./components/FocusedOverview";
import { Navigation } from "./components/Navigation";
import { SideDrawer } from "./components/SideDrawer";
import { TaskResult } from "./components/TaskResult";
import { TaskDetails, TaskOverview } from "./components/TaskDetails";
import { statusLabel, taskMessage } from "./components/taskFormat";
import { Toast, type ToastMessage } from "./components/Toast";
import { pageFromHash, pageMeta, type PageKey } from "./pageConfig";
import { BillsPage } from "./pages/BillsPage";
import { CardsPage } from "./pages/CardsPage";
import { InvestmentsPage } from "./pages/InvestmentsPage";
import { SubscriptionsPage } from "./pages/SubscriptionsPage";
import { TransfersPage } from "./pages/TransfersPage";

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  task?: AgentTaskResponse;
};
type ApiState = "checking" | "connected" | "unavailable";
type RecoveryAction = "connection" | "task" | "write-lookup" | "write-retry";
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
const demoEntryStorageKey = "finorch.demo.entered.v1";

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => unknown;
};

function readDemoEntry(): boolean {
  try {
    return sessionStorage.getItem(demoEntryStorageKey) === "1";
  } catch {
    return false;
  }
}

function withViewTransition(update: () => void) {
  const transitionDocument = document as ViewTransitionDocument;
  const reducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  if (transitionDocument.startViewTransition && !reducedMotion) {
    transitionDocument.startViewTransition(update);
  } else {
    update();
  }
}

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
  const isNetworkError = isNetworkFailure(error);
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
          银行卡、账单和订阅均为模拟数据，不连接真实银行或支付服务。
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
  const suggestions = [
    "我这个月花了多少钱",
    "最近有没有异常消费",
    "我有哪些自动扣费",
    "查询我的账户余额",
    "查看我的转账记录",
    "查看适合我的理财产品",
  ];
  const activeCard = cards.find((item) => item.status === "active");
  if (activeCard)
    suggestions.push("冻结尾号 " + activeCard.card_suffix + " 的卡");
  return suggestions;
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
  const [enteredDemo, setEnteredDemo] = useState(readDemoEntry);
  const [activePage, setActivePage] = useState<PageKey>(pageFromHash);
  const [contextOpen, setContextOpen] = useState(initialContextOpen);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsDrawerOpen, setDetailsDrawerOpen] = useState(false);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [toast, setToast] = useState<ToastMessage | null>(null);
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
    setConfirmationOpen(Boolean(task.confirmation));
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

  const dismissToast = useCallback(() => setToast(null), []);
  const closeConfirmation = useCallback(() => setConfirmationOpen(false), []);
  const closeDetailsDrawer = useCallback(() => {
    setDetailsDrawerOpen(false);
    setDetailsOpen(false);
  }, []);

  const notify = useCallback(
    (title: string, message: string, tone: ToastMessage["tone"]) => {
      setToast({
        id: crypto.randomUUID(),
        title,
        message,
        tone,
      });
    },
    [],
  );

  const navigate = useCallback((page: PageKey) => {
    withViewTransition(() => {
      setActivePage(page);
      setMobileNavOpen(false);
      window.history.pushState(null, "", "#/" + page);
      window.scrollTo({ top: 0, behavior: "smooth" });
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
            if (recovered.task) applyTask(recovered.task);
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
            if (current && recent) applyTask(recent);
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
    function onHashChange() {
      withViewTransition(() => {
        setActivePage(pageFromHash());
        setMobileNavOpen(false);
      });
    }
    if (!window.location.hash) {
      window.history.replaceState(null, "", "#/overview");
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
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

  async function submitWrite(write: PendingWrite) {
    storePendingWrite(write);
    setBusy(true);
    setRequestError(null);
    try {
      const task = await executeWrite(write);
      applyTask(task);
      storePendingWrite(null);
      if (task.status === "completed") {
        notify("任务已完成", task.message, "success");
      } else if (task.status === "awaiting_confirmation") {
        notify("等待你的确认", "操作尚未执行，请核对后再确认。", "warning");
      } else if (task.status === "failed") {
        notify("操作未完成", taskMessage(task), "error");
      }
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
          return;
        }
      } catch {
        // Keep the idempotency record so the user can query or safely retry it later.
      }
      setRequestError(toUiError(error));
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
      if (task.status === "completed") {
        notify("任务已完成", task.message, "success");
      } else if (task.status === "awaiting_confirmation") {
        notify("等待你的确认", "操作尚未执行，请核对后再确认。", "warning");
      }
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
      if (task) applyTask(task);
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
    setDraft("");
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", text: requestText },
    ]);
    const key = crypto.randomUUID();
    const hasCompletedStep = activeTask?.steps.some(
      (step) => step.step_type === "tool" && step.status === "succeeded",
    );
    const canContinueFailedTask =
      activeTask?.status === "failed" && hasCompletedStep;
    const write: PendingWrite =
      activeTask &&
      (["awaiting_input", "awaiting_confirmation"].includes(
        activeTask.status,
      ) ||
        canContinueFailedTask)
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

  function askFinOrch(prompt: string) {
    navigate("assistant");
    void sendMessage(prompt);
  }

  function enterDemo() {
    withViewTransition(() => {
      try {
        sessionStorage.setItem(demoEntryStorageKey, "1");
      } catch {
        // Entry state is a presentation aid, not an authorization source.
      }
      setEnteredDemo(true);
      setActivePage("overview");
      window.history.replaceState(null, "", "#/overview");
    });
  }

  function exitDemo() {
    withViewTransition(() => {
      try {
        sessionStorage.removeItem(demoEntryStorageKey);
      } catch {
        // Ignore storage restrictions; the current session can still exit.
      }
      setEnteredDemo(false);
    });
  }

  const mode = activeTask?.provider_mode ?? session?.agent_provider ?? "fake";
  const overviewRefreshKey = activeTask
    ? `${activeTask.id}:${activeTask.version}`
    : (session?.dataset_version ?? "initial");
  const demoDisplayName =
    !session || session.display_name === "Demo User One"
      ? "林知远"
      : userName(session);

  if (!enteredDemo) {
    return (
      <DemoGate
        apiState={apiState}
        onEnter={enterDemo}
        onRetry={() => void retryConnection()}
        session={session}
      />
    );
  }

  return (
    <div className="app-shell">
      <Navigation
        activePage={activePage}
        displayName={demoDisplayName}
        mobileOpen={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
        onExit={exitDemo}
        onNavigate={navigate}
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
              <div className="topbar-path">
                <span>FinOrch</span>
                <i aria-hidden="true">/</i>
                <strong>{pageMeta(activePage).label}</strong>
              </div>
            </div>
            <div className="topbar-actions">
              <button
                className="topbar-new-task"
                onClick={() => {
                  navigate("assistant");
                  document.getElementById("agent-request")?.focus();
                }}
                type="button"
              >
                <span aria-hidden="true">+</span>
                新任务
              </button>
              <EnvironmentDetails
                apiVersion={apiVersion}
                mode={mode}
                session={session}
              />
              <StatusIndicator status={apiState} />
              <button
                aria-label="退出演示账户"
                className="account-avatar"
                onClick={exitDemo}
                title="退出演示"
                type="button"
              >
                LZ
              </button>
            </div>
          </div>
        </header>

        <main className="page-content">
          {activePage === "overview" ? (
            <FocusedOverview
              activeTask={activeTask}
              audit={audit}
              busy={busy}
              cards={cards}
              onPrompt={askFinOrch}
              refreshKey={overviewRefreshKey}
              session={session}
            />
          ) : null}

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

          {activePage === "assistant" ? (
            <>
              <div className="workspace-stage-heading">
                <div>
                  <p className="eyebrow">Agent workspace</p>
                  <h2>把目标交给 FinOrch，先理解，再执行</h2>
                </div>
                <span>
                  <AppIcon name="info" size={15} />
                  所有变更以服务端结果为准
                </span>
              </div>

              <div className="workbench-grid">
                <section
                  aria-labelledby="assistant-title"
                  className="assistant-panel"
                  id="assistant"
                >
                  <div className="assistant-header">
                    <div>
                      <h2 id="assistant-title">对话</h2>
                      <p>银行卡、账单、订阅、转账与理财</p>
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
                            : "可以查询模拟账户和账单，也可以在确认后发起转账、管理订阅或操作模拟理财。"}
                        </p>
                        {!loading ? (
                          <div className="suggestion-group">
                            <span className="suggestion-label">你可以试试</span>
                            <div className="suggestions">
                              {promptSuggestions(cards).map((prompt) => (
                                <button
                                  className="suggestion-button"
                                  disabled={
                                    busy || Boolean(pendingWrite) || !session
                                  }
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
                                <TaskResult task={message.task} />
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
                    {pendingWrite ? (
                      <p className="composer-hint">
                        上一项请求状态尚未确认，请先查询结果或使用相同请求安全重试。
                      </p>
                    ) : activeTask?.status === "awaiting_input" ? (
                      <p className="composer-hint">补充信息将继续当前任务。</p>
                    ) : activeTask?.status === "awaiting_confirmation" ? (
                      <p className="composer-hint">
                        修改请求会取消当前确认，并重新核对操作内容。
                      </p>
                    ) : activeTask?.status === "failed" &&
                      activeTask.steps.some(
                        (step) =>
                          step.step_type === "tool" &&
                          step.status === "succeeded",
                      ) ? (
                      <p className="composer-hint">
                        部分步骤已完成；补充要求可继续当前任务，已完成操作不会重做。
                      </p>
                    ) : null}
                    <label className="visually-hidden" htmlFor="agent-request">
                      输入请求
                    </label>
                    <div className="composer-row">
                      <textarea
                        id="agent-request"
                        disabled={Boolean(pendingWrite)}
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
                        placeholder="例如：我这个月花了多少钱"
                        rows={2}
                        value={draft}
                      />
                      <button
                        aria-label="发送请求"
                        className="send-button"
                        disabled={
                          busy ||
                          Boolean(pendingWrite) ||
                          !draft.trim() ||
                          !session
                        }
                        type="submit"
                      >
                        <AppIcon name="send" size={19} />
                      </button>
                    </div>
                    <div className="composer-foot">
                      <span>Enter 发送，Shift + Enter 换行</span>
                      <span>仅处理模拟数据</span>
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
                      <strong>执行上下文</strong>
                      <small>账户、卡片与处理进度</small>
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
                      manageDisabled={busy || Boolean(pendingWrite)}
                      onManage={(card) =>
                        void sendMessage(
                          card.status === "active"
                            ? `冻结尾号 ${card.card_suffix} 的银行卡`
                            : `解冻尾号 ${card.card_suffix} 的银行卡`,
                        )
                      }
                      onRefresh={() => void refreshCards()}
                      refreshing={refreshing}
                    />
                    <TaskOverview
                      busy={busy}
                      refreshing={refreshingTask}
                      onRefresh={() => void refreshTask()}
                      onCancel={() => {
                        if (activeTask) void cancelTask(activeTask);
                      }}
                      onOpenConfirmation={() => {
                        setDetailsDrawerOpen(false);
                        setConfirmationOpen(true);
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
            </>
          ) : null}

          {activePage === "bills" ? (
            <BillsPage busy={busy} onPrompt={askFinOrch} />
          ) : null}
          {activePage === "cards" ? (
            <CardsPage
              busy={busy || Boolean(pendingWrite)}
              cards={cards}
              loading={loading}
              onManage={(card) =>
                askFinOrch(
                  card.status === "active"
                    ? `冻结尾号 ${card.card_suffix} 的银行卡`
                    : `解冻尾号 ${card.card_suffix} 的银行卡`,
                )
              }
              onPrompt={askFinOrch}
              onRefresh={() => void refreshCards()}
              refreshing={refreshing}
            />
          ) : null}
          {activePage === "transfers" ? (
            <TransfersPage busy={busy} onPrompt={askFinOrch} />
          ) : null}
          {activePage === "subscriptions" ? (
            <SubscriptionsPage
              busy={busy || Boolean(pendingWrite)}
              onPrompt={askFinOrch}
              refreshKey={overviewRefreshKey}
            />
          ) : null}
          {activePage === "investments" ? (
            <InvestmentsPage busy={busy} onPrompt={askFinOrch} />
          ) : null}
        </main>
      </div>

      <nav aria-label="移动端快捷导航" className="mobile-dock">
        <button
          aria-current={activePage === "overview" ? "page" : undefined}
          className={activePage === "overview" ? "mobile-dock-active" : ""}
          onClick={() => navigate("overview")}
          type="button"
        >
          <AppIcon name="overview" size={19} />
          <span>总览</span>
        </button>
        <button
          aria-current={activePage === "assistant" ? "page" : undefined}
          className={activePage === "assistant" ? "mobile-dock-active" : ""}
          onClick={() => navigate("assistant")}
          type="button"
        >
          <AppIcon name="assistant" size={19} />
          <span>助手</span>
        </button>
        <button
          aria-current={activePage === "bills" ? "page" : undefined}
          className={activePage === "bills" ? "mobile-dock-active" : ""}
          onClick={() => navigate("bills")}
          type="button"
        >
          <AppIcon name="bill" size={19} />
          <span>账单</span>
        </button>
        <button
          aria-current={activePage === "cards" ? "page" : undefined}
          className={activePage === "cards" ? "mobile-dock-active" : ""}
          onClick={() => navigate("cards")}
          type="button"
        >
          <AppIcon name="cards" size={19} />
          <span>卡片</span>
        </button>
        <button onClick={() => setMobileNavOpen(true)} type="button">
          <AppIcon name="menu" size={19} />
          <span>更多</span>
        </button>
      </nav>

      {activeTask?.confirmation && confirmationOpen ? (
        <ConfirmationModal
          busy={busy}
          confirmation={activeTask.confirmation}
          onCancel={() => void cancelTask(activeTask)}
          onClose={closeConfirmation}
          onConfirm={() => void confirmTask(activeTask)}
        />
      ) : null}

      {detailsDrawerOpen ? (
        <SideDrawer
          onClose={closeDetailsDrawer}
          subtitle="Task evidence and audit"
          title="执行记录"
        >
          <TaskOverview
            busy={busy}
            onCancel={() => {
              if (activeTask) void cancelTask(activeTask);
            }}
            onOpenConfirmation={() => {
              setDetailsDrawerOpen(false);
              setConfirmationOpen(true);
            }}
            onRefresh={() => void refreshTask()}
            refreshing={refreshingTask}
            task={activeTask}
          />
          <TaskDetails
            audit={audit}
            auditError={auditError}
            auditLoading={auditLoading}
            onOpenChange={setDetailsOpen}
            open
            task={activeTask}
          />
        </SideDrawer>
      ) : null}

      {toast ? <Toast onDismiss={dismissToast} toast={toast} /> : null}
    </div>
  );
}
