import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import {
  ApiError,
  apiClient,
  type AccountBalanceListResponse,
  type AgentTaskResponse,
  type AuditResponse,
  type BillSummaryResponse,
  type SubscriptionListResponse,
  type TransactionPageResponse,
} from "../api/client";
import { AppIcon } from "./AppIcon";
import { SkeletonLine } from "./Skeleton";
import { statusLabel } from "./taskFormat";
import { customerText } from "../userFacing";

type OverviewData = {
  accounts: AccountBalanceListResponse;
  bills: BillSummaryResponse;
  subscriptions: SubscriptionListResponse;
  transactions: TransactionPageResponse;
};

type OverviewDialog = "transactions" | "transaction" | "risk" | "audit" | null;
type Transaction = TransactionPageResponse["items"][number];
type AuditEvent = AuditResponse["events"][number];
type TransactionFilter = "all" | "income" | "expense" | "attention";

function money(
  valueMinor: number | null | undefined,
  currencyCode = "CNY",
  fractionDigits = 2,
) {
  if (valueMinor === null || valueMinor === undefined) return "—";
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: currencyCode,
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(valueMinor / 100);
}

function transactionDate(value: string) {
  const date = new Date(value);
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  const time = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
  if (sameDay) return `今天 ${time}`;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function auditTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function auditCopy(event: AuditEvent) {
  const labels: Record<string, string> = {
    task_created: "创建办理任务",
    task_confirmed: "确认了操作",
    task_cancelled: "取消了任务",
    tool_succeeded: "完成了一项操作",
    tool_failed: "操作未能完成",
    confirmation_requested: "等待操作确认",
    confirmation_succeeded: "确认通过",
    "transfer.executed": "完成转账",
    "transfer.scheduled": "创建预约转账",
    "transfer.cancelled": "取消预约转账",
    "split.status_changed": "更新 AA 分账状态",
    "subscription.status_changed": "更新自动扣费状态",
    "investment.buy_executed": "完成理财申购",
    "investment.sell_executed": "完成理财赎回",
    "card.status_changed": "更新银行卡状态",
    "card.replaced": "完成银行卡补发",
  };
  const resources: Record<string, string> = {
    card: "银行卡",
    card_application: "银行卡申请",
    subscription: "自动扣费",
    transfer: "转账",
    split: "AA 分账",
    investment_order: "理财",
    task: "任务",
    confirmation: "操作确认",
    demo_user: "账户安全",
    transaction: "交易",
  };
  const outcomes: Record<string, string> = {
    succeeded: "已完成",
    failed: "未完成",
    blocked: "已拦截",
    issued: "已生成",
    pending: "待处理",
    approved: "已通过",
    rejected: "未通过",
    cancelled: "已取消",
  };
  return {
    title: labels[event.event_type] ?? "操作记录",
    detail: `${resources[event.resource_type] ?? "相关业务"} · ${outcomes[event.outcome] ?? "状态已更新"}`,
  };
}

function OverviewDialog({
  children,
  className = "",
  onClose,
  title,
}: {
  children: ReactNode;
  className?: string;
  onClose: () => void;
  title: string;
}) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  return createPortal(
    <div
      className="overview-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="presentation"
    >
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className={`overview-dialog-panel ${className}`}
        role="dialog"
      >
        <header className="overview-dialog-header">
          <h2 id={titleId}>{title}</h2>
          <button
            aria-label="关闭弹窗"
            className="overview-dialog-close"
            onClick={onClose}
            ref={closeRef}
            type="button"
          >
            关闭
            <span aria-hidden="true">×</span>
          </button>
        </header>
        {children}
      </section>
    </div>,
    document.body,
  );
}

function TransactionRow({
  compact = false,
  onSelect,
  transaction,
}: {
  compact?: boolean;
  onSelect: () => void;
  transaction: Transaction;
}) {
  const attention = Boolean(transaction.anomaly_reason);
  const amount = `${transaction.direction === "income" ? "+" : "−"}${money(transaction.amount_minor, transaction.currency)}`;

  if (compact) {
    return (
      <button
        aria-label={`${transaction.merchant}，${transaction.category}，${amount}，${transactionDate(transaction.occurred_at)}${attention ? "，需要核对" : ""}`}
        className="overview-transaction-row overview-transaction-row-compact"
        onClick={onSelect}
        type="button"
      >
        <span
          aria-hidden="true"
          className={`overview-transaction-direction ${transaction.direction}`}
        >
          {transaction.direction === "income" ? "+" : "−"}
        </span>
        <span className="overview-transaction-copy">
          <strong>{transaction.merchant}</strong>
          <span>
            {transaction.category} <i aria-hidden="true">·</i>{" "}
            {transactionDate(transaction.occurred_at)}
          </span>
        </span>
        <span className="overview-transaction-trailing">
          <strong
            className={
              transaction.direction === "income"
                ? "overview-transaction-amount is-income"
                : "overview-transaction-amount"
            }
          >
            {amount}
          </strong>
          {attention ? <small>需核对</small> : null}
        </span>
      </button>
    );
  }

  return (
    <button
      className="overview-transaction-row"
      onClick={onSelect}
      type="button"
    >
      <span className="overview-transaction-date">
        {transactionDate(transaction.occurred_at)}
      </span>
      <strong>{transaction.merchant}</strong>
      <span>{transaction.category}</span>
      <span className="overview-transaction-amount">{amount}</span>
      {attention ? (
        <span className="overview-transaction-status is-attention">需核对</span>
      ) : null}
    </button>
  );
}

export function FocusedOverview({
  refreshKey,
  activeTask,
  busy,
  onOpenAssistant,
  onPrompt,
}: {
  refreshKey: string;
  activeTask: AgentTaskResponse | null;
  busy: boolean;
  onOpenAssistant: () => void;
  onPrompt: (prompt: string) => void;
}) {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<OverviewDialog>(() => {
    const previewDialog = sessionStorage.getItem("finorch.preview.dialog");
    sessionStorage.removeItem("finorch.preview.dialog");
    return previewDialog === "transactions" ||
      previewDialog === "risk" ||
      previewDialog === "audit"
      ? previewDialog
      : null;
  });
  const [transactionFilter, setTransactionFilter] =
    useState<TransactionFilter>("all");
  const [selectedTransaction, setSelectedTransaction] =
    useState<Transaction | null>(null);
  const [auditModal, setAuditModal] = useState<{
    taskId: string;
    events: AuditEvent[];
    error: string | null;
  } | null>(null);
  const auditTaskId = activeTask?.id;
  const auditTaskVersion = activeTask?.version;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [accounts, bills, subscriptions, transactions] = await Promise.all([
        apiClient.readAccounts(),
        apiClient.readBillSummary(),
        apiClient.readSubscriptions(),
        apiClient.readTransactions({ limit: 20 }),
      ]);
      setData({ accounts, bills, subscriptions, transactions });
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : "暂时无法读取财务总览。",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshKey]);

  useEffect(() => {
    if (dialog !== "audit") return;
    if (!auditTaskId) return;
    let current = true;
    apiClient
      .readAudit(auditTaskId)
      .then((result) => {
        if (current) {
          setAuditModal({
            taskId: auditTaskId,
            events: result.events,
            error: null,
          });
        }
      })
      .catch((caught: unknown) => {
        if (current) {
          setAuditModal({
            taskId: auditTaskId,
            events: [],
            error:
              caught instanceof Error
                ? caught.message
                : "暂时无法读取操作记录。",
          });
        }
      });
    return () => {
      current = false;
    };
  }, [auditTaskId, auditTaskVersion, dialog]);

  const currencyCode =
    data?.accounts.items[0]?.currency ?? data?.bills.currency ?? "CNY";
  const billCurrencyCode = data?.bills.currency ?? currencyCode;
  const totalBalance =
    data?.accounts.items.reduce(
      (total, account) => total + account.available_balance_minor,
      0,
    ) ?? null;
  const leadingAnomaly = data?.bills.anomalies[0] ?? null;
  const riskTransaction = selectedTransaction?.anomaly_reason
    ? selectedTransaction
    : leadingAnomaly;
  const showTaskAttention = Boolean(
    activeTask &&
    [
      "pending",
      "planning",
      "awaiting_input",
      "awaiting_confirmation",
      "running",
      "failed",
    ].includes(activeTask.status),
  );
  const activeSubscriptions =
    data?.subscriptions.items.filter((item) => item.status === "active") ?? [];
  const dateLabel = new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(new Date());
  const anomalyPrompt = riskTransaction
    ? `核对${riskTransaction.merchant}的这笔交易，金额 ${money(riskTransaction.amount_minor, riskTransaction.currency)}${riskTransaction.source_card_suffix ? `，银行卡尾号 ${riskTransaction.source_card_suffix}` : ""}。请先说明账单提示依据，再给出处理建议。`
    : "检查本月异常消费，并先展示判断证据";

  const filteredTransactions = useMemo(() => {
    const items = data?.transactions.items ?? [];
    if (transactionFilter === "income") {
      return items.filter((item) => item.direction === "income");
    }
    if (transactionFilter === "expense") {
      return items.filter((item) => item.direction === "expense");
    }
    if (transactionFilter === "attention") {
      return items.filter((item) => Boolean(item.anomaly_reason));
    }
    return items;
  }, [data?.transactions.items, transactionFilter]);

  const visibleTransactions = filteredTransactions.slice(0, 8);
  const recentTransactions = data?.transactions.items.slice(0, 5) ?? [];
  const matchingAuditModal =
    activeTask && auditModal?.taskId === activeTask.id ? auditModal : null;
  const auditLoading =
    dialog === "audit" && Boolean(activeTask) && !matchingAuditModal;
  const auditEvents = matchingAuditModal
    ? matchingAuditModal.events.slice(-6).map((event) => {
        const copy = auditCopy(event);
        return {
          time: auditTime(event.occurred_at),
          title: copy.title,
          detail: copy.detail,
        };
      })
    : [];

  const exportTransactions = () => {
    const rows = [
      ["时间", "交易", "分类", "金额", "币种", "提醒"],
      ...filteredTransactions.map((transaction) => [
        transaction.occurred_at,
        transaction.merchant,
        transaction.category,
        (transaction.amount_minor / 100).toFixed(2),
        transaction.currency,
        transaction.anomaly_reason ? "需核对" : "—",
      ]),
    ];
    const csv = rows
      .map((row) =>
        row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(","),
      )
      .join("\n");
    const url = URL.createObjectURL(
      new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "finorch-transactions.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="focused-overview">
      <header className="overview-page-heading">
        <h1>账户总览</h1>
        <time>{dateLabel}</time>
      </header>

      <section aria-label="账户资金" className="overview-funds">
        <div className="overview-balance-block">
          <div className="overview-balance-heading">
            <p className="overview-balance-label">可用余额</p>
            <span>{data?.accounts.items.length ?? 0} 个账户</span>
          </div>
          <p className="overview-balance-value">
            {loading ? (
              <SkeletonLine
                className="focused-balance-skeleton"
                width="320px"
              />
            ) : (
              money(totalBalance, currencyCode)
            )}
          </p>
          <div className="overview-balance-meta">
            <span>
              {data?.bills.net_minor !== undefined && data.bills.net_minor < 0
                ? "本月净流出"
                : "本月净流入"}
            </span>
            <strong>
              {loading
                ? "读取中"
                : money(data?.bills.net_minor, billCurrencyCode)}
            </strong>
          </div>
        </div>

        <div className="overview-monthly-summary">
          <div>
            <span>本月收入</span>
            <strong>
              {loading
                ? "—"
                : money(data?.bills.income_minor, billCurrencyCode)}
            </strong>
          </div>
          <div>
            <span>本月支出</span>
            <strong>
              {loading
                ? "—"
                : money(data?.bills.expense_minor, billCurrencyCode)}
            </strong>
          </div>
        </div>
      </section>

      <div className="overview-main-grid">
        <section
          aria-labelledby="recent-transactions-title"
          className="overview-transactions"
        >
          <header>
            <h2 id="recent-transactions-title">最近交易</h2>
            <button
              className="overview-text-action"
              onClick={() => setDialog("transactions")}
              type="button"
            >
              查看全部
            </button>
          </header>
          {loading ? (
            <div className="skeleton-rows" aria-label="正在读取交易">
              {Array.from({ length: 4 }, (_, index) => (
                <div className="skeleton-row" key={index}>
                  <span className="skeleton-avatar" />
                  <span className="skeleton-row-copy">
                    <span />
                    <span />
                  </span>
                  <span className="skeleton-amount" />
                </div>
              ))}
            </div>
          ) : recentTransactions.length ? (
            <div className="overview-transaction-list">
              {recentTransactions.map((transaction) => (
                <TransactionRow
                  compact
                  key={transaction.id}
                  onSelect={() => {
                    setSelectedTransaction(transaction);
                    setDialog("transaction");
                  }}
                  transaction={transaction}
                />
              ))}
            </div>
          ) : (
            <p className="page-empty">还没有交易记录。</p>
          )}
        </section>

        <aside className="overview-side-column">
          <section
            aria-labelledby="attention-title"
            className="overview-attention-panel"
          >
            <header className="overview-attention-heading">
              <h2 id="attention-title">需要关注</h2>
              <span>
                {(showTaskAttention ? 1 : 0) +
                  (leadingAnomaly ? (data?.bills.anomalies.length ?? 0) : 0)}
                项
              </span>
            </header>
            <div className="overview-attention-list">
              {showTaskAttention && activeTask ? (
                <button
                  className="overview-attention-item overview-task-attention"
                  onClick={onOpenAssistant}
                  type="button"
                >
                  <span
                    aria-hidden="true"
                    className="overview-attention-symbol"
                  >
                    {activeTask.status === "failed" ? "!" : "…"}
                  </span>
                  <span className="overview-attention-copy">
                    <strong>
                      {activeTask.status === "awaiting_confirmation"
                        ? "等待你确认"
                        : activeTask.status === "awaiting_input"
                          ? "需要补充信息"
                          : activeTask.status === "failed"
                            ? "任务未能继续"
                            : "任务正在处理"}
                    </strong>
                    {activeTask.message ? (
                      <small>{activeTask.message}</small>
                    ) : null}
                  </span>
                  <AppIcon name="arrow-right" size={16} />
                </button>
              ) : null}
              {leadingAnomaly ? (
                <button
                  className="overview-attention-item overview-anomaly-attention"
                  disabled={busy}
                  onClick={() => {
                    setSelectedTransaction(null);
                    setDialog("risk");
                  }}
                  type="button"
                >
                  <span
                    aria-hidden="true"
                    className="overview-attention-symbol"
                  >
                    !
                  </span>
                  <span className="overview-attention-copy">
                    <strong>
                      {data?.bills.anomalies.length ?? 0} 笔交易需核对
                    </strong>
                    <small>{leadingAnomaly.merchant}</small>
                  </span>
                  <strong className="overview-attention-amount">
                    {money(
                      leadingAnomaly.amount_minor,
                      leadingAnomaly.currency,
                    )}
                  </strong>
                </button>
              ) : null}
              {!showTaskAttention && !leadingAnomaly ? (
                <p className="overview-attention-empty">
                  暂时没有需要处理的事项。
                </p>
              ) : null}
            </div>
          </section>

          <div className="overview-quick-links">
            <button
              onClick={() => onPrompt("我有哪些自动扣费，下一次什么时候扣款")}
              type="button"
            >
              <span>自动扣费</span>
              <strong>{activeSubscriptions.length} 项</strong>
              <AppIcon name="arrow-right" size={16} />
            </button>
            <button onClick={() => setDialog("audit")} type="button">
              <span>操作记录</span>
              <AppIcon name="arrow-right" size={16} />
            </button>
          </div>
        </aside>
      </div>

      {error ? (
        <div className="focused-overview-error" role="alert">
          <span>{error}</span>
          <button onClick={() => void load()} type="button">
            重新读取
          </button>
        </div>
      ) : null}

      {dialog === "transaction" && selectedTransaction ? (
        <OverviewDialog
          className="overview-transaction-dialog"
          onClose={() => setDialog(null)}
          title={selectedTransaction.merchant}
        >
          <div className="overview-transaction-detail">
            <p
              className={
                selectedTransaction.direction === "income" ? "is-income" : ""
              }
            >
              {selectedTransaction.direction === "income" ? "+" : "−"}
              {money(
                selectedTransaction.amount_minor,
                selectedTransaction.currency,
              )}
            </p>
            <dl>
              <div>
                <dt>时间</dt>
                <dd>{transactionDate(selectedTransaction.occurred_at)}</dd>
              </div>
              <div>
                <dt>类别</dt>
                <dd>{selectedTransaction.category}</dd>
              </div>
              <div>
                <dt>付款卡</dt>
                <dd>
                  {selectedTransaction.source_card_suffix
                    ? `尾号 ${selectedTransaction.source_card_suffix}`
                    : "未关联银行卡"}
                </dd>
              </div>
            </dl>
            {selectedTransaction.anomaly_reason ? (
              <div className="overview-transaction-evidence">
                <strong>需要核对</strong>
                <p>{customerText(selectedTransaction.anomaly_reason)}</p>
                <button
                  className="overview-primary-action"
                  onClick={() => setDialog("risk")}
                  type="button"
                >
                  查看提醒
                  <AppIcon name="arrow-right" size={14} />
                </button>
              </div>
            ) : null}
          </div>
        </OverviewDialog>
      ) : null}

      {dialog === "transactions" ? (
        <OverviewDialog
          className="overview-transactions-dialog"
          onClose={() => setDialog(null)}
          title="最近交易"
        >
          <div
            className="overview-filter-row"
            role="group"
            aria-label="交易筛选"
          >
            {[
              ["all", "全部"],
              ["income", "收入"],
              ["expense", "支出"],
              ["attention", "需核对"],
            ].map(([value, label]) => (
              <button
                className={transactionFilter === value ? "is-active" : ""}
                key={value}
                onClick={() => setTransactionFilter(value as TransactionFilter)}
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
          <div className="overview-table-head" aria-hidden="true">
            <span>时间</span>
            <span>交易</span>
            <span>分类</span>
            <span>金额</span>
            <span>提醒</span>
          </div>
          <div className="overview-transaction-list">
            {visibleTransactions.map((transaction) => (
              <TransactionRow
                key={transaction.id}
                onSelect={() => {
                  setSelectedTransaction(transaction);
                  setDialog("transaction");
                }}
                transaction={transaction}
              />
            ))}
            {!visibleTransactions.length ? (
              <p className="overview-dialog-empty">当前筛选没有交易。</p>
            ) : null}
          </div>
          <footer className="overview-dialog-footer">
            <span>
              {filteredTransactions.length} 笔记录 · 本月净现金流{" "}
              {money(data?.bills.net_minor, currencyCode)}
            </span>
            <button onClick={exportTransactions} type="button">
              导出明细 →
            </button>
          </footer>
        </OverviewDialog>
      ) : null}

      {dialog === "risk" ? (
        <OverviewDialog
          className="overview-risk-dialog"
          onClose={() => setDialog(null)}
          title={riskTransaction ? "需要核对的一笔交易" : "本月没有交易提醒"}
        >
          {riskTransaction ? (
            <>
              <div className="overview-risk-amount">
                <span>商户</span>
                <h3>{riskTransaction.merchant}</h3>
                <strong>
                  {money(
                    riskTransaction.amount_minor,
                    riskTransaction.currency,
                  )}
                </strong>
              </div>
              <dl className="overview-risk-meta">
                <div>
                  <dt>时间</dt>
                  <dd>{transactionDate(riskTransaction.occurred_at)}</dd>
                </div>
                <div>
                  <dt>类别</dt>
                  <dd>{riskTransaction.category}</dd>
                </div>
                <div>
                  <dt>账户</dt>
                  <dd>
                    {riskTransaction.source_card_suffix
                      ? `银行卡 ·•• ${riskTransaction.source_card_suffix}`
                      : "银行卡信息不可用"}
                  </dd>
                </div>
              </dl>
              <div className="overview-risk-evidence">
                <p>为什么被标记</p>
                <div>
                  <i />
                  <span>
                    <strong>
                      {customerText(riskTransaction.anomaly_reason)}
                    </strong>
                    <small>账单规则提醒，仅供核对，不代表欺诈结论。</small>
                  </span>
                </div>
              </div>
              <div className="overview-risk-actions">
                <button onClick={() => setDialog(null)} type="button">
                  关闭
                </button>
                <button
                  className="overview-primary-action"
                  disabled={busy}
                  onClick={() => {
                    setDialog(null);
                    onPrompt(anomalyPrompt);
                  }}
                  type="button"
                >
                  请助手核对
                  <AppIcon name="arrow-right" size={14} />
                </button>
              </div>
            </>
          ) : (
            <div className="overview-dialog-empty">
              当前账户暂无符合规则的异常提醒。
            </div>
          )}
        </OverviewDialog>
      ) : null}

      {dialog === "audit" ? (
        <OverviewDialog
          className="overview-audit-dialog"
          onClose={() => setDialog(null)}
          title="操作记录"
        >
          <div className="overview-audit-summary">
            <span>
              {auditLoading
                ? "正在读取操作记录…"
                : `${auditEvents.length} 条操作记录`}
            </span>
            <small>
              {activeTask ? statusLabel(activeTask.status) : "当前没有办理任务"}
            </small>
          </div>
          {matchingAuditModal?.error ? (
            <p className="overview-dialog-empty" role="alert">
              {matchingAuditModal.error}
            </p>
          ) : auditLoading ? (
            <p aria-live="polite" className="overview-dialog-empty">
              正在读取…
            </p>
          ) : auditEvents.length ? (
            <ol className="overview-audit-list">
              {auditEvents.map((event, index) => (
                <li key={`${event.time}-${event.title}-${index}`}>
                  <i />
                  <time>{event.time}</time>
                  <span>
                    <strong>{event.title}</strong>
                    <small>{event.detail}</small>
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="overview-dialog-empty">当前没有可查看的操作记录。</p>
          )}
        </OverviewDialog>
      ) : null}
    </section>
  );
}
