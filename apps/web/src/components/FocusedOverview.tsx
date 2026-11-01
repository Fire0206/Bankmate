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
  type CardListResponse,
  type SubscriptionListResponse,
  type TransactionPageResponse,
} from "../api/client";
import { AppIcon } from "./AppIcon";
import { CashflowChart } from "./CashflowChart";
import { SkeletonLine } from "./Skeleton";
import { statusLabel } from "./taskFormat";
import { customerText } from "../userFacing";

type OverviewData = {
  accounts: AccountBalanceListResponse;
  bills: BillSummaryResponse;
  subscriptions: SubscriptionListResponse;
  transactions: TransactionPageResponse;
};

type OverviewDialog = "transactions" | "risk" | "audit" | null;
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
    task_created: "创建处理任务",
    task_confirmed: "完成关键动作确认",
    task_cancelled: "取消任务",
    tool_succeeded: "操作完成",
    tool_failed: "操作未完成",
    confirmation_requested: "生成确认挑战",
    confirmation_succeeded: "确认校验通过",
  };
  return labels[event.event_type] ?? event.event_type.replaceAll("_", " ");
}

function OverviewDialog({
  children,
  className = "",
  eyebrow,
  onClose,
  subtitle,
  title,
}: {
  children: ReactNode;
  className?: string;
  eyebrow: string;
  onClose: () => void;
  subtitle?: string;
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
      className="figma-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="presentation"
    >
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className={`figma-modal-panel ${className}`}
        role="dialog"
      >
        <header className="figma-modal-header">
          <div>
            <p className="figma-modal-eyebrow">{eyebrow}</p>
            <h2 id={titleId}>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          <button
            aria-label="关闭弹窗"
            className="figma-modal-close"
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
  onSelect,
  transaction,
}: {
  onSelect: () => void;
  transaction: Transaction;
}) {
  const attention = Boolean(transaction.anomaly_reason);
  return (
    <button className="figma-transaction-row" onClick={onSelect} type="button">
      <span className="figma-transaction-date">
        {transactionDate(transaction.occurred_at)}
      </span>
      <strong>{transaction.merchant}</strong>
      <span>{transaction.category}</span>
      <span
        className={
          transaction.direction === "income"
            ? "figma-transaction-amount is-income"
            : "figma-transaction-amount"
        }
      >
        {transaction.direction === "income" ? "+" : "−"}
        {money(transaction.amount_minor, transaction.currency)}
      </span>
      <span
        className={
          attention
            ? "figma-transaction-status is-attention"
            : "figma-transaction-status"
        }
      >
        {attention ? "待确认" : "已完成"}
      </span>
    </button>
  );
}

export function FocusedOverview({
  cards,
  refreshKey,
  activeTask,
  audit,
  busy,
  onPrompt,
}: {
  cards: CardListResponse["items"];
  refreshKey: string;
  activeTask: AgentTaskResponse | null;
  audit: AuditEvent[];
  busy: boolean;
  onPrompt: (prompt: string) => void;
}) {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<OverviewDialog>(() => {
    const previewDialog = sessionStorage.getItem("bankmate.preview.dialog");
    sessionStorage.removeItem("bankmate.preview.dialog");
    return previewDialog === "transactions" ||
      previewDialog === "risk" ||
      previewDialog === "audit"
      ? previewDialog
      : null;
  });
  const [transactionFilter, setTransactionFilter] =
    useState<TransactionFilter>("all");

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

  const currencyCode =
    data?.accounts.items[0]?.currency ?? data?.bills.currency ?? "CNY";
  const totalBalance =
    data?.accounts.items.reduce(
      (total, account) => total + account.balance_minor,
      0,
    ) ?? null;
  const leadingAnomaly = data?.bills.anomalies[0] ?? null;
  const activeSubscriptions =
    data?.subscriptions.items.filter((item) => item.status === "active") ?? [];
  const frozenCards = cards.filter((card) => card.status === "frozen").length;
  const dateLabel = new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(new Date());
  const anomalyPrompt = leadingAnomaly
    ? `处理异常扣款：${leadingAnomaly.merchant}，金额 ${money(leadingAnomaly.amount_minor, leadingAnomaly.currency)}，卡片尾号 ${leadingAnomaly.source_card_suffix ?? "1042"}。请先展示证据，再给出冻结或继续观察的建议。`
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
  const auditEvents = activeTask
    ? audit.slice(-6).map((event) => ({
        time: auditTime(event.occurred_at),
        title: auditCopy(event),
        detail: `${event.resource_type} · ${event.outcome}`,
      }))
    : [];

  const exportTransactions = () => {
    const rows = [
      ["时间", "交易", "分类", "金额", "币种", "状态"],
      ...filteredTransactions.map((transaction) => [
        transaction.occurred_at,
        transaction.merchant,
        transaction.category,
        (transaction.amount_minor / 100).toFixed(2),
        transaction.currency,
        transaction.anomaly_reason ? "待确认" : "已完成",
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
    anchor.download = "bankmate-transactions.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="focused-overview">
      <div className="focused-overview-meta">
        <span>账户总览</span>
        <span>{dateLabel}</span>
      </div>

      <div className="focused-balance">
        <p>可用余额</p>
        <h1>
          {loading ? (
            <SkeletonLine className="focused-balance-skeleton" width="380px" />
          ) : (
            money(totalBalance, currencyCode)
          )}
        </h1>
        <div className="focused-balance-meta">
          <strong>
            {loading
              ? "读取中"
              : `${data?.bills.net_minor && data.bills.net_minor > 0 ? "+" : ""}${money(data?.bills.net_minor, currencyCode)}`}
          </strong>
          <span>本月净现金流</span>
          <i />
          <span>{data?.accounts.items.length ?? 0} 个账户</span>
        </div>
      </div>

      {leadingAnomaly ? (
        <button
          className="focused-risk-line"
          disabled={busy}
          onClick={() => setDialog("risk")}
          type="button"
        >
          <i aria-hidden="true" />
          <span>
            {data?.bills.anomalies.length ?? 0} 笔交易待确认 ·{" "}
            {leadingAnomaly.merchant}
          </span>
          <strong>
            {money(leadingAnomaly.amount_minor, leadingAnomaly.currency)}
          </strong>
          <AppIcon name="arrow-right" size={14} />
        </button>
      ) : (
        <div className="focused-risk-line is-clear">
          <i aria-hidden="true" />
          <span>本月暂未命中异常规则</span>
        </div>
      )}

      <section className="focused-cashflow">
        <header>
          <div>
            <h2>现金流</h2>
            <span>近 6 个月</span>
          </div>
          <small>近六个月收支记录</small>
        </header>
        {loading ? (
          <div aria-hidden="true" className="focused-chart-skeleton">
            {Array.from({ length: 8 }, (_, index) => (
              <i key={index} />
            ))}
          </div>
        ) : data?.bills.trends.length ? (
          <CashflowChart
            expenseMinor={data.bills.expense_minor}
            height={285}
            incomeMinor={data.bills.income_minor}
            trends={data.bills.trends}
          />
        ) : (
          <div className="focused-chart-empty">暂无可展示的现金流趋势</div>
        )}
        <div className="focused-cashflow-summary">
          <span>
            本月收入
            <strong>{money(data?.bills.income_minor, currencyCode)}</strong>
          </span>
          <span>
            本月支出
            <strong>{money(data?.bills.expense_minor, currencyCode)}</strong>
          </span>
          <span className="focused-outlook">
            <i />
            自动扣费{" "}
            {money(data?.subscriptions.monthly_total_minor, currencyCode)}
          </span>
        </div>
      </section>

      <div className="focused-entry-row">
        <button onClick={() => setDialog("transactions")} type="button">
          <span>
            最近交易
            <AppIcon name="arrow-right" size={14} />
          </span>
          <strong>{data?.transactions.total ?? 0} 笔新记录</strong>
          <small>过去 48 小时与本月活动</small>
        </button>
        <button
          className={leadingAnomaly ? "has-risk" : ""}
          onClick={() => setDialog("risk")}
          type="button"
        >
          <span>
            可疑扣款
            <AppIcon name="arrow-right" size={14} />
          </span>
          <strong>
            {leadingAnomaly
              ? money(leadingAnomaly.amount_minor, leadingAnomaly.currency)
              : "暂无异常提醒"}
          </strong>
          <small>{leadingAnomaly ? "需要你核对" : "账单记录正常"}</small>
        </button>
        <button onClick={() => setDialog("audit")} type="button">
          <span>
            处置记录
            <AppIcon name="arrow-right" size={14} />
          </span>
          <strong>{audit.length} 个事件</strong>
          <small>查看操作过程与结果</small>
        </button>
      </div>

      <footer className="focused-overview-footer">
        <span>
          <i /> 本地账户 · 不接入真实银行
        </span>
        <span>
          {frozenCards} 张卡已冻结 · {activeSubscriptions.length} 项自动扣费
        </span>
        <span>资金操作需确认</span>
      </footer>

      {error ? (
        <div className="focused-overview-error" role="alert">
          <span>{error}</span>
          <button onClick={() => void load()} type="button">
            重新读取
          </button>
        </div>
      ) : null}

      {dialog === "transactions" ? (
        <OverviewDialog
          className="figma-transactions-dialog"
          eyebrow="账户活动"
          onClose={() => setDialog(null)}
          subtitle="过去一段时间内的账户活动。可疑项不会被自动处置。"
          title="最近交易"
        >
          <div className="figma-filter-row" role="group" aria-label="交易筛选">
            {[
              ["all", "全部"],
              ["income", "收入"],
              ["expense", "支出"],
              ["attention", "待确认"],
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
          <div className="figma-table-head" aria-hidden="true">
            <span>时间</span>
            <span>交易</span>
            <span>分类</span>
            <span>金额</span>
            <span>状态</span>
          </div>
          <div className="figma-transaction-list">
            {visibleTransactions.map((transaction) => (
              <TransactionRow
                key={transaction.id}
                onSelect={() => {
                  setDialog(
                    transaction.anomaly_reason ? "risk" : "transactions",
                  );
                }}
                transaction={transaction}
              />
            ))}
            {!visibleTransactions.length ? (
              <p className="figma-dialog-empty">当前筛选没有交易。</p>
            ) : null}
          </div>
          <footer className="figma-dialog-footer">
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
          className="figma-risk-dialog"
          eyebrow="风险提示与待处理"
          onClose={() => setDialog(null)}
          title={leadingAnomaly ? "一笔交易需要你的确认" : "本月暂未发现异常"}
        >
          {leadingAnomaly ? (
            <>
              <div className="figma-risk-amount">
                <span>商户</span>
                <h3>{leadingAnomaly.merchant}</h3>
                <strong>
                  {money(leadingAnomaly.amount_minor, leadingAnomaly.currency)}
                </strong>
              </div>
              <dl className="figma-risk-meta">
                <div>
                  <dt>时间</dt>
                  <dd>{transactionDate(leadingAnomaly.occurred_at)}</dd>
                </div>
                <div>
                  <dt>类别</dt>
                  <dd>{leadingAnomaly.category}</dd>
                </div>
                <div>
                  <dt>账户</dt>
                  <dd>
                    主账户借记卡 ·••
                    {leadingAnomaly.source_card_suffix ?? "1042"}
                  </dd>
                </div>
              </dl>
              <div className="figma-risk-evidence">
                <p>为什么被标记</p>
                <div>
                  <i />
                  <span>
                    <strong>
                      {customerText(leadingAnomaly.anomaly_reason)}
                    </strong>
                    <small>根据交易记录发出的核对提醒。</small>
                  </span>
                </div>
                <div>
                  <i />
                  <span>
                    <strong>卡片处于可操作状态</strong>
                    <small>冻结等高风险动作仍需二次确认。</small>
                  </span>
                </div>
                <div>
                  <i />
                  <span>
                    <strong>本地账户</strong>
                    <small>操作不会触达真实资金。</small>
                  </span>
                </div>
              </div>
              <div className="figma-risk-actions">
                <button onClick={() => setDialog(null)} type="button">
                  这可能是我的交易
                </button>
                <button
                  className="figma-primary-action"
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
            <div className="figma-dialog-empty">
              当前账户暂无符合规则的异常提醒。
            </div>
          )}
        </OverviewDialog>
      ) : null}

      {dialog === "audit" ? (
        <OverviewDialog
          className="figma-audit-dialog"
          eyebrow="操作记录"
          onClose={() => setDialog(null)}
          subtitle="每一次调用、判断、证据和确认都会进入可追溯记录。"
          title="处置记录"
        >
          <div className="figma-audit-summary">
            <span>{auditEvents.length} 条操作记录</span>
            <small>
              {activeTask ? statusLabel(activeTask.status) : "账户记录"}
            </small>
          </div>
          <ol className="figma-audit-list">
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
          <div className="figma-audit-footer">
            <span>所有关键动作都需要明确确认</span>
            <small>展示本次操作的处理结果</small>
          </div>
        </OverviewDialog>
      ) : null}
    </section>
  );
}
