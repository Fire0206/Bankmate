import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiClient } from "./api/client";
import type {
  AgentTaskHistoryResponse,
  AgentTaskResponse,
  AuditResponse,
  CardListResponse,
  DemoSessionResponse,
} from "./api/client";
import { AppIcon } from "./components/AppIcon";
import { CardList } from "./components/CardList";
import { ConfirmationModal } from "./components/ConfirmationModal";
import { FocusedOverview } from "./components/FocusedOverview";
import { Navigation } from "./components/Navigation";
import { SideDrawer } from "./components/SideDrawer";
import { TaskResult } from "./components/TaskResult";
import { TaskDetails, TaskOverview } from "./components/TaskDetails";
import { TaskHandoffAction } from "./components/TaskHandoffAction";
import { TaskHistory } from "./components/TaskHistory";
import { statusLabel, taskMessage } from "./components/taskFormat";
import { Toast, type ToastMessage } from "./components/Toast";
import { pageFromHash, pageMeta, type PageKey } from "./pageConfig";
import { BillsPage } from "./pages/BillsPage";
import { CardsPage } from "./pages/CardsPage";
import { InvestmentsPage } from "./pages/InvestmentsPage";
import { SubscriptionsPage } from "./pages/SubscriptionsPage";
import { TransfersPage } from "./pages/TransfersPage";
import { brand } from "./brand";
import { customerName } from "./userFacing";

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

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void) => unknown;
};

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
  strong_verification_required: "请先完成账户安全验证。",
  verification_incorrect: "验证码不正确，请核对后重试。",
  verification_expired: "验证码已过期，请取消并重新发起操作。",
  verification_invalidated: "风险或操作内容已变化，请取消并重新发起。",
  verification_locked: "验证码尝试次数已用尽，请取消并重新发起。",
  verification_unavailable: "这次验证已失效，请刷新任务状态。",
  safety_hold_active:
    "出于安全考虑，暂时无法执行这项操作。查询仍可使用，请稍后重试。",
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
  if (!session) return "正在读取";
  return customerName(session.display_name);
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

function StatusIndicator({ status }: { status: ApiState }) {
  const copy = {
    checking: "正在连接",
    connected: "",
    unavailable: "暂时无法连接",
  }[status];
  if (status === "connected") return null;
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

function AccountDetails({
  mode,
  externalModelEgressEnabled,
}: {
  mode: DemoSessionResponse["agent_provider"];
  externalModelEgressEnabled: boolean;
}) {
  return (
    <details className="environment-details">
      <summary>账户说明</summary>
      <div className="environment-popover">
        <h2>账户与服务</h2>
        <p>
          账户、交易和产品信息使用本地数据。操作只更新本地账户记录，不会触达真实资金。
        </p>
        <p className="environment-note">
          {mode === "fake"
            ? "请求在本机处理，不会发送到外部服务。"
            : externalModelEgressEnabled
              ? "已启用外部服务。你的输入和完成请求所需的本地账户信息会发送至配置的服务，请勿输入真实个人信息。"
              : "外部服务未启用，请求不会发送到外部。"}
        </p>
      </div>
    </details>
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
  const [conversationId, setConversationId] = useState(conversationKey);
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [session, setSession] = useState<DemoSessionResponse | null>(null);
  const [cards, setCards] = useState<CardListResponse["items"]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [activeTask, setActiveTask] = useState<AgentTaskResponse | null>(null);
  const [taskHistory, setTaskHistory] = useState<
    AgentTaskHistoryResponse["items"]
  >([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(() => {
    try {
      // Remove pending request bodies left by older builds. Recovery reads
      // authoritative task state from the server instead of browser storage.
      sessionStorage.removeItem("finorch.demo.pending-write");
    } catch {
      // Storage may be disabled; task recovery still works through the API.
    }
    return null;
  });
  const [auditState, setAuditState] = useState<{
    key: string;
    events: AuditResponse["events"];
    error: ApiError | Error | null;
  } | null>(null);
  const [draft, setDraft] = useState("");
  const [taskSwitchRequest, setTaskSwitchRequest] = useState<string | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshingTask, setRefreshingTask] = useState(false);
  const [recoveryAction, setRecoveryAction] = useState<RecoveryAction | null>(
    null,
  );
  const [requestError, setRequestError] = useState<UiError | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [activePage, setActivePage] = useState<PageKey>(pageFromHash);
  const [contextOpen, setContextOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailsDrawerOpen, setDetailsDrawerOpen] = useState(false);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLElement>(null);
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
      const withoutTask = current.filter(
        (message) => message.task?.id !== task.id,
      );
      if (withoutTask.length === 0) {
        return [
          {
            id: "task-request-" + task.id,
            role: "user",
            text: task.request_text,
          },
          response,
        ];
      }
      return [...withoutTask, response];
    });
  }, []);

  const refreshTaskHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const response = await apiClient.readTaskHistory(30);
      setTaskHistory(response.items);
      setHistoryError(null);
    } catch (error) {
      setHistoryError(
        error instanceof Error ? error.message : "暂时无法读取办理记录。",
      );
    } finally {
      setHistoryLoading(false);
    }
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
      window.requestAnimationFrame(() => {
        mainRef.current?.focus({ preventScroll: true });
      });
    });
  }, []);

  const startNewConversation = useCallback(() => {
    const nextConversationId = crypto.randomUUID();
    try {
      sessionStorage.setItem("finorch.demo.conversation", nextConversationId);
    } catch {
      // Storage may be disabled; the in-memory conversation remains isolated.
    }
    setConversationId(nextConversationId);
    setMessages([]);
    setActiveTask(null);
    setAuditState(null);
    setRequestError(null);
    setDraft("");
    setConfirmationOpen(false);
    setDetailsOpen(false);
    navigate("assistant");
    window.requestAnimationFrame(() => {
      document.getElementById("agent-request")?.focus();
    });
  }, [navigate]);

  const storePendingWrite = useCallback((write: PendingWrite | null) => {
    setPendingWrite(write);
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
      })
      .catch((error: unknown) => {
        if (!current) return;
        setApiState("unavailable");
        setRequestError(toUiError(error));
      });

    Promise.all([apiClient.readSession(), apiClient.readCards()])
      .then(async ([demo, cardPage]) => {
        if (!current) return;
        setSession(demo);
        setCards(cardPage.items);
        try {
          const recent = await apiClient.readRecentTask(conversationId);
          if (current && recent) applyTask(recent);
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
  }, [applyTask, conversationId]);

  useEffect(() => {
    let current = true;
    apiClient
      .readTaskHistory(30)
      .then((response) => {
        if (!current) return;
        setTaskHistory(response.items);
        setHistoryError(null);
      })
      .catch((error: unknown) => {
        if (!current) return;
        setHistoryError(
          error instanceof Error ? error.message : "暂时无法读取办理记录。",
        );
      })
      .finally(() => {
        if (current) setHistoryLoading(false);
      });
    return () => {
      current = false;
    };
  }, []);

  useEffect(() => {
    function onHashChange() {
      withViewTransition(() => {
        setActivePage(pageFromHash());
        setMobileNavOpen(false);
        window.requestAnimationFrame(() => {
          mainRef.current?.focus({ preventScroll: true });
        });
      });
    }
    if (!window.location.hash) {
      window.history.replaceState(null, "", "#/overview");
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

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
          if (current) {
            applyTask(task);
            if (task.status !== activeTaskStatus) void refreshTaskHistory();
          }
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
  }, [activeTaskId, activeTaskStatus, applyTask, refreshTaskHistory]);

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

  async function executeWrite(
    write: PendingWrite,
    verificationCode?: string,
  ): Promise<AgentTaskResponse> {
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
        verificationCode,
      );
    }
    return apiClient.cancelTask(write.taskId, write.key);
  }

  async function submitWrite(
    write: PendingWrite,
    verificationCode?: string,
  ): Promise<AgentTaskResponse | null> {
    storePendingWrite(write);
    setBusy(true);
    setRequestError(null);
    try {
      const task = await executeWrite(write, verificationCode);
      applyTask(task);
      await refreshTaskHistory();
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
      return task;
    } catch (error) {
      try {
        const recovered = await lookupPendingWrite(write);
        if (recovered.task) {
          applyTask(recovered.task);
          await refreshTaskHistory();
        }
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
      if (recovered.task) {
        applyTask(recovered.task);
        await refreshTaskHistory();
      }
      if (recovered.resolved) {
        storePendingWrite(null);
        if (recovered.task?.status === "completed") await refreshCards();
        return;
      }
      if (!allowResubmit) {
        setRequestError({
          title: "暂时无法确认处理结果",
          message: recovered.task
            ? "请求已保存，可以继续查看进度，或用相同内容安全重试。"
            : "暂时没有查到这次请求的处理结果。请使用原请求继续尝试。",
          code: null,
          status: null,
          requestId: null,
          fieldDetails: [],
        });
        return;
      }
      const task = await executeWrite(pendingWrite);
      applyTask(task);
      await refreshTaskHistory();
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
        if (latest.task) {
          applyTask(latest.task);
          await refreshTaskHistory();
        }
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
      await refreshTaskHistory();
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
      await refreshTaskHistory();
      if (task.status === "completed") await refreshCards();
      setRequestError(null);
    } catch (error) {
      setRequestError(toUiError(error));
    } finally {
      setRefreshingTask(false);
    }
  }

  async function sendMessage(value = draft, continueActiveTask = false) {
    const requestText = value.trim();
    if (!requestText || busy || !session || pendingWrite) return;
    const needsTaskChoice =
      activeTask &&
      ["awaiting_input", "awaiting_confirmation"].includes(activeTask.status);
    if (needsTaskChoice && !continueActiveTask) {
      setTaskSwitchRequest(requestText);
      setDraft("");
      return;
    }
    setTaskSwitchRequest(null);
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
    const continuingTask =
      activeTask &&
      (["awaiting_input", "awaiting_confirmation"].includes(
        activeTask.status,
      ) ||
        canContinueFailedTask);
    const taskConversationId = continuingTask
      ? activeTask.conversation_id
      : conversationId;
    const write: PendingWrite =
      continuingTask && activeTask
        ? {
            kind: "input",
            key,
            conversationId: taskConversationId,
            taskId: activeTask.id,
            requestText,
          }
        : {
            kind: "create",
            key,
            conversationId: taskConversationId,
            requestText,
          };
    await submitWrite(write);
  }

  async function resolveTaskSwitch(choice: "continue" | "new") {
    const requestText = taskSwitchRequest;
    const task = activeTask;
    if (!requestText || !task || busy || pendingWrite) return;
    if (choice === "continue") {
      setTaskSwitchRequest(null);
      await sendMessage(requestText, true);
      return;
    }

    if (task.status !== "cancelled") {
      const cancelled = await submitWrite({
        kind: "cancel",
        key: crypto.randomUUID(),
        conversationId: task.conversation_id,
        taskId: task.id,
      });
      if (cancelled?.status !== "cancelled") return;
    }

    const nextConversationId = crypto.randomUUID();
    try {
      sessionStorage.setItem("finorch.demo.conversation", nextConversationId);
    } catch {
      // The new task still uses a fresh in-memory conversation ID.
    }
    setConversationId(nextConversationId);
    setActiveTask(null);
    setAuditState(null);
    setConfirmationOpen(false);
    setTaskSwitchRequest(null);
    setMessages([{ id: crypto.randomUUID(), role: "user", text: requestText }]);
    await submitWrite({
      kind: "create",
      key: crypto.randomUUID(),
      conversationId: nextConversationId,
      requestText,
    });
  }

  async function confirmTask(
    task: AgentTaskResponse,
    verificationCode?: string,
  ) {
    if (!task.confirmation || busy) return;
    await submitWrite(
      {
        kind: "confirm",
        key: task.confirmation.idempotency_key,
        conversationId: task.conversation_id,
        taskId: task.id,
        challengeId: task.confirmation.id,
        parametersHash: task.confirmation.parameters_hash,
      },
      verificationCode,
    );
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

  function askAssistant(prompt: string) {
    navigate("assistant");
    void sendMessage(prompt);
  }

  async function openHistoryTask(taskId: string) {
    if (busy || pendingWrite) return;
    setRequestError(null);
    try {
      const task = await apiClient.readTask(taskId);
      setMessages([
        {
          id: "history-request-" + task.id,
          role: "user",
          text: task.request_text,
        },
      ]);
      applyTask(task);
      setConfirmationOpen(Boolean(task.confirmation));
      await refreshTaskHistory();
    } catch (error) {
      setRequestError(toUiError(error));
    }
  }

  const overviewRefreshKey = activeTask
    ? `${activeTask.id}:${activeTask.version}`
    : (session?.dataset_version ?? "initial");
  const displayName = customerName(session?.display_name);

  return (
    <div className="app-shell">
      <a className="skip-to-content" href="#main-content">
        跳到主要内容
      </a>
      <Navigation
        activePage={activePage}
        displayName={displayName}
        mobileOpen={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
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
                <span>{brand.name}</span>
                <i aria-hidden="true">/</i>
                <strong>{pageMeta(activePage).label}</strong>
              </div>
            </div>
            <div className="topbar-actions">
              <button
                className="topbar-new-task"
                onClick={startNewConversation}
                type="button"
              >
                <span aria-hidden="true">+</span>
                新对话
              </button>
              <AccountDetails
                mode={
                  activeTask?.provider_mode ?? session?.agent_provider ?? "fake"
                }
                externalModelEgressEnabled={
                  session?.external_model_egress_enabled ?? false
                }
              />
              <StatusIndicator status={apiState} />
              <span
                aria-label={`当前账户：${displayName}`}
                className="account-avatar"
                title={displayName}
              >
                {displayName.slice(0, 2)}
              </span>
            </div>
          </div>
        </header>

        <main
          className={"page-content page-" + activePage}
          id="main-content"
          ref={mainRef}
          tabIndex={-1}
        >
          {activePage === "overview" ? (
            <FocusedOverview
              activeTask={activeTask}
              audit={audit}
              busy={busy}
              cards={cards}
              onPrompt={askAssistant}
              refreshKey={overviewRefreshKey}
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
              <div className="assistant-page-heading">
                <h1>智能助手</h1>
              </div>

              <div className="workbench-grid">
                <section
                  aria-label="智能助手对话"
                  className="assistant-panel"
                  id="assistant"
                >
                  <div
                    aria-live="polite"
                    className="conversation"
                    ref={conversationRef}
                    role="log"
                  >
                    {messages.length === 0 ? (
                      <div className="welcome-state">
                        <h2>今天想处理什么？</h2>
                        <p>
                          {loading
                            ? "正在读取账户…"
                            : "查询收支、管理银行卡，或安排一项资金操作。"}
                        </p>
                        {!loading ? (
                          <div className="suggestion-group">
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
                                : brand.name}
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
                                <TaskHandoffAction task={message.task} />
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
                    className={
                      "composer" +
                      (messages.length === 0 ? " composer-empty" : "")
                    }
                    onSubmit={(event) => {
                      event.preventDefault();
                      void sendMessage();
                    }}
                  >
                    {taskSwitchRequest ? (
                      <div
                        aria-label="选择任务处理方式"
                        className="task-switch-prompt"
                        role="group"
                      >
                        <div>
                          <strong>当前任务尚未结束</strong>
                          <p>
                            “{taskSwitchRequest}
                            ”要继续当前任务，还是开始新任务？
                          </p>
                          <small>
                            开始新任务会取消当前待处理请求；已经完成的操作不会撤销。
                          </small>
                        </div>
                        <div className="task-switch-actions">
                          <button
                            disabled={busy || Boolean(pendingWrite)}
                            onClick={() => void resolveTaskSwitch("continue")}
                            type="button"
                          >
                            继续当前任务
                          </button>
                          <button
                            disabled={busy || Boolean(pendingWrite)}
                            onClick={() => void resolveTaskSwitch("new")}
                            type="button"
                          >
                            取消当前任务并开始新任务
                          </button>
                        </div>
                      </div>
                    ) : null}
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
                      <span>资金操作需确认</span>
                    </div>
                  </form>
                </section>

                <TaskHistory
                  disabled={busy || Boolean(pendingWrite)}
                  error={historyError}
                  items={taskHistory}
                  loading={historyLoading}
                  onRefresh={() => void refreshTaskHistory()}
                  onSelect={(taskId) => void openHistoryTask(taskId)}
                  selectedId={activeTask?.id}
                />

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
                      <strong>账户与任务</strong>
                      <small>银行卡和办理进度</small>
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
            <BillsPage busy={busy} onPrompt={askAssistant} />
          ) : null}
          {activePage === "cards" ? (
            <CardsPage
              busy={busy || Boolean(pendingWrite)}
              cards={cards}
              loading={loading}
              onManage={(card) =>
                askAssistant(
                  card.status === "active"
                    ? `冻结尾号 ${card.card_suffix} 的银行卡`
                    : `解冻尾号 ${card.card_suffix} 的银行卡`,
                )
              }
              onPrompt={askAssistant}
              onRefresh={() => void refreshCards()}
              refreshing={refreshing}
            />
          ) : null}
          {activePage === "transfers" ? (
            <TransfersPage busy={busy} onPrompt={askAssistant} />
          ) : null}
          {activePage === "subscriptions" ? (
            <SubscriptionsPage
              busy={busy || Boolean(pendingWrite)}
              onPrompt={askAssistant}
              refreshKey={overviewRefreshKey}
            />
          ) : null}
          {activePage === "investments" ? (
            <InvestmentsPage busy={busy} onPrompt={askAssistant} />
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
      </nav>

      {activeTask?.confirmation && confirmationOpen ? (
        <ConfirmationModal
          busy={busy}
          confirmation={activeTask.confirmation}
          hasPreviousChanges={activeTask.steps.some(
            (step) => step.step_type === "tool" && step.status === "succeeded",
          )}
          onCancel={() => void cancelTask(activeTask)}
          onClose={closeConfirmation}
          onConfirm={(code) => void confirmTask(activeTask, code)}
          onRefresh={() => void refreshTask()}
          refreshing={refreshingTask}
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
