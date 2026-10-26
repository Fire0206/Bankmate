import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { ApiError, apiClient } from "../api/client";
import { brand } from "../brand";
import type {
  AccountListResponse,
  AgentTaskResponse,
  AuditResponse,
  BillSummaryResponse,
  CardListResponse,
  CreateTaskRequest,
  DemoSessionResponse,
  OrderListResponse,
  PaydayPlanPreviewRequest,
  PaydayPlanPreviewResponse,
  PayeeListResponse,
  PortfolioResponse,
  ProductListResponse,
  RecommendationsResponse,
  RiskProfileResponse,
  SplitListResponse,
  SubscriptionListResponse,
  TaskInputRequest,
  TransactionsResponse,
  TransferListResponse,
} from "../api/client";
import "./showcase.css";

type PageId =
  | "overview"
  | "assistant"
  | "cards"
  | "bills"
  | "transfers"
  | "subscriptions"
  | "investments"
  | "cross-scene";
type ShowcaseData = {
  health: Awaited<ReturnType<typeof apiClient.readHealth>>;
  session: DemoSessionResponse;
  cards: CardListResponse;
  transactions: TransactionsResponse;
  bills: BillSummaryResponse;
  subscriptions: SubscriptionListResponse;
  accounts: AccountListResponse;
  payees: PayeeListResponse;
  transfers: TransferListResponse;
  splits: SplitListResponse;
  products: ProductListResponse;
  portfolio: PortfolioResponse;
  risk: RiskProfileResponse;
  orders: OrderListResponse;
  recommendations: RecommendationsResponse;
};
type Confirmation = NonNullable<AgentTaskResponse["confirmation"]>;
type PendingCreate = { key: string; body: CreateTaskRequest };
type PageItem = { id: PageId; label: string; number: string };

const pageItems: PageItem[] = [
  { id: "overview", label: "账户总览", number: "01" },
  { id: "assistant", label: "智能助手", number: "02" },
  { id: "cards", label: "银行卡", number: "03" },
  { id: "bills", label: "账单分析", number: "04" },
  { id: "transfers", label: "转账与分账", number: "05" },
  { id: "subscriptions", label: "订阅代扣", number: "06" },
  { id: "investments", label: "理财", number: "07" },
  { id: "cross-scene", label: "跨场景计划", number: "08" },
];

const labelMap: Record<string, string> = {
  account_label: "账户",
  amount_minor: "金额（分）",
  category: "类别",
  currency: "币种",
  direction: "收支方向",
  expense_minor: "支出（分）",
  income_minor: "收入（分）",
  merchant: "商户",
  month: "月份",
  net_minor: "收支结余（分）",
  product_name: "产品",
  status: "状态",
  title: "名称",
  transfer_amount_minor: "转账金额（分）",
};

const toolLabelMap: Record<string, string> = {
  "bill.anomalies": "检查账单提示",
  "bill.monthly_summary": "汇总月度账单",
  "bill.transactions": "查询交易明细",
  "card.freeze": "冻结银行卡",
  "card.get": "查看银行卡详情",
  "card.list": "查询银行卡",
  "card.unfreeze": "解冻银行卡",
  "finance.payday_plan": "预览发薪日计划",
  "investment.buy": "准备申购",
  "investment.compare": "比较理财产品",
  "investment.orders": "查询理财记录",
  "investment.portfolio": "查询持仓",
  "investment.profile": "查询风险承受能力",
  "investment.products": "查询理财产品",
  "investment.redeem": "准备赎回",
  "subscription.cancel": "准备取消自动续费",
  "subscription.list": "查询订阅",
  "subscription.pause": "准备暂停自动续费",
  "subscription.resume": "准备恢复自动续费",
  "transfer.accounts": "查询账户余额",
  "transfer.cancel_scheduled": "准备取消定时转账",
  "transfer.create": "准备转账",
  "transfer.history": "查询转账记录",
  "transfer.payees": "查询收款人",
  "transfer.schedule": "准备定时转账",
  "transfer.simulate_due": "模拟执行已确认的定时转账",
  "transfer.split_collect": "准备收取分账",
  "transfer.split_create": "准备创建分账",
  "transfer.splits": "查询分账记录",
};

const errorLabelMap: Record<string, string> = {
  card_not_found: "未找到这张银行卡。",
  insufficient_funds: "可用余额不足，未执行操作。",
  risk_mismatch: "该产品与当前演示风险等级不匹配。",
  subscription_not_found: "未找到对应的订阅。",
  transfer_payee_not_found: "未找到对应的收款人。",
};

const auditEventLabelMap: Record<string, string> = {
  "agent.duplicate_write_suppressed": "已拦截重复请求",
  "agent.task_cancelled": "任务已取消",
  "agent.task_created": "任务已创建",
  "agent.task_input_received": "收到补充信息",
  "agent.task_state_changed": "任务状态更新",
  "agent.tool_execution_failed": "业务步骤未完成",
  "agent.tool_execution_succeeded": "业务步骤已完成",
  "agent.workflow_continued": "任务继续执行",
  "card.status_changed": "银行卡状态已更新",
  "investment.buy_executed": "模拟申购已执行",
  "investment.redeem_executed": "模拟赎回已执行",
  "split.status_changed": "分账状态已更新",
  "subscription.status_changed": "订阅状态已更新",
  "transfer.cancelled": "定时转账已取消",
  "transfer.executed": "模拟转账已执行",
  "transfer.scheduled": "定时转账已创建",
  "transfer.simulated_execution_failed": "定时转账模拟执行失败",
};

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

function conversationId(): string {
  const key = "finorch.showcase.conversation";
  const stored = window.localStorage.getItem(key);
  if (stored) return stored;
  const value = crypto.randomUUID();
  window.localStorage.setItem(key, value);
  return value;
}

function money(
  amountMinor: number | null | undefined,
  currency = "CNY",
): string {
  if (amountMinor === null || amountMinor === undefined) return "—";
  const sign = amountMinor < 0 ? "−" : "";
  const absolute = Math.abs(amountMinor);
  const major = Math.floor(absolute / 100).toLocaleString("zh-CN");
  const minor = String(absolute % 100).padStart(2, "0");
  const symbol = currency === "CNY" ? "¥" : currency + " ";
  return `${sign}${symbol}${major}.${minor}`;
}

function amountToMinor(value: string): number | null {
  const match = /^(\d{1,8})(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match) return null;
  const cents =
    BigInt(match[1]) * 100n + BigInt((match[2] ?? "").padEnd(2, "0"));
  if (cents > BigInt(Number.MAX_SAFE_INTEGER)) return null;
  return Number(cents);
}

function dateLabel(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("zh-CN", {
        month: "numeric",
        day: "numeric",
      }).format(date);
}

function dateTimeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
}

function statusName(status: string): string {
  const labels: Record<string, string> = {
    active: "正常",
    frozen: "已冻结",
    pending_confirmation: "待确认",
    due_for_confirmation: "到期待确认",
    paused: "已暂停",
    cancelled: "已取消",
    awaiting_confirmation: "等待确认",
    awaiting_input: "等待补充",
    planning: "正在规划",
    running: "正在处理",
    pending: "待处理",
    queued: "待处理",
    succeeded: "已完成",
    completed: "已完成",
    failed: "未完成",
    scheduled: "待执行",
    executed: "已执行",
    lost: "已挂失",
    replaced: "已补卡",
    submitted: "已提交",
    updated: "已更新",
    paid: "已支付",
    open: "待收款",
    settled: "已结清",
  };
  return labels[status] ?? status;
}

function stepLabel(step: AgentTaskResponse["steps"][number]): string {
  if (step.tool_name) return toolLabelMap[step.tool_name] ?? "处理业务请求";
  if (step.step_type === "planner") return "分析请求";
  if (step.step_type === "input") return "接收补充信息";
  if (step.step_type === "confirmation") return "执行已确认操作";
  return "处理任务";
}

function auditEventLabel(eventType: string): string {
  const exact = auditEventLabelMap[eventType];
  if (exact) return exact;
  if (eventType.endsWith(".confirmation_requested")) return "等待用户确认";
  if (eventType.endsWith(".confirmation_consumed")) return "用户确认已使用";
  if (eventType.endsWith(".confirmation_expired")) return "确认已过期";
  if (eventType.endsWith(".confirmation_invalidated")) return "旧确认已失效";
  if (eventType.endsWith(".confirmation_rejected")) return "确认操作被拒绝";
  return "操作记录";
}

function apiMessage(error: unknown): string {
  if (error instanceof ApiError)
    return `${error.message}${error.requestId ? `（请求编号 ${error.requestId}）` : ""}`;
  return error instanceof Error ? error.message : "暂时无法读取服务数据。";
}

function useShowcaseData(month: string) {
  const [data, setData] = useState<ShowcaseData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [
        health,
        session,
        cards,
        transactions,
        bills,
        subscriptions,
        accounts,
        payees,
        transfers,
        splits,
        products,
        portfolio,
        risk,
        orders,
        recommendations,
      ] = await Promise.all([
        apiClient.readHealth(),
        apiClient.readSession(),
        apiClient.readCards(),
        apiClient.readTransactions(month),
        apiClient.readBillSummary(month),
        apiClient.readSubscriptions(),
        apiClient.readAccounts(),
        apiClient.readPayees(),
        apiClient.readTransfers(),
        apiClient.readSplits(),
        apiClient.readProducts(),
        apiClient.readPortfolio(),
        apiClient.readRiskProfile(),
        apiClient.readOrders(),
        apiClient.readRecommendations(month),
      ]);
      setData({
        health,
        session,
        cards,
        transactions,
        bills,
        subscriptions,
        accounts,
        payees,
        transfers,
        splits,
        products,
        portfolio,
        risk,
        orders,
        recommendations,
      });
    } catch (reason) {
      setError(apiMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  return { data, loading, error, refresh };
}

function LogoMark() {
  return (
    <span aria-hidden="true" className="showcase-logo-mark">
      {brand.mark}
    </span>
  );
}

function Metric({
  label,
  value,
  detail,
  tone = "plain",
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "plain" | "accent";
}) {
  return (
    <div className={`showcase-metric showcase-metric-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function SectionTitle({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="showcase-section-title">
      <div>
        <h2>{title}</h2>
        {hint ? <p>{hint}</p> : null}
      </div>
      {action}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="showcase-empty">{text}</p>;
}

function CardTile({ item }: { item: CardListResponse["items"][number] }) {
  return (
    <article
      className={`showcase-bank-card ${item.status === "frozen" ? "is-frozen" : ""}`}
    >
      <div className="showcase-bank-card-top">
        <span>{brand.name.toUpperCase()}</span>
        <span>{item.status === "active" ? "借记卡" : "已冻结"}</span>
      </div>
      <div className="showcase-bank-card-chip" aria-hidden="true">
        <i />
        <i />
        <i />
        <i />
      </div>
      <p className="showcase-card-number">
        •••• &nbsp;•••• &nbsp;•••• &nbsp;{item.card_suffix}
      </p>
      <div className="showcase-bank-card-bottom">
        <strong>{item.label}</strong>
        <span>{item.status === "active" ? "正常" : "已冻结"}</span>
      </div>
    </article>
  );
}

function TransactionTable({ items }: { items: TransactionsResponse["items"] }) {
  if (!items.length) return <EmptyState text="所选月份暂无交易记录。" />;
  return (
    <div className="showcase-table-wrap">
      <table className="showcase-table">
        <thead>
          <tr>
            <th>商户 / 说明</th>
            <th>类别</th>
            <th>日期</th>
            <th className="align-right">金额</th>
          </tr>
        </thead>
        <tbody>
          {items.slice(0, 8).map((item) => (
            <tr key={item.id}>
              <td>
                <strong>{item.merchant}</strong>
                {item.anomaly_reason ? (
                  <small className="showcase-risk-copy">
                    {item.anomaly_reason}
                  </small>
                ) : null}
              </td>
              <td>{item.category}</td>
              <td>{dateLabel(item.occurred_at)}</td>
              <td
                className={`align-right ${item.direction === "income" ? "showcase-positive" : ""}`}
              >
                {item.direction === "income" ? "+" : "−"}
                {money(item.amount_minor, item.currency)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RecommendationList({ data }: { data: RecommendationsResponse }) {
  if (!data.items.length)
    return <EmptyState text="目前没有需要特别留意的账单提示。" />;
  return (
    <div className="showcase-recommendations">
      {data.items.map((item) => (
        <article className="showcase-recommendation" key={item.id}>
          <span
            className={`showcase-priority priority-${item.priority}`}
            aria-hidden="true"
          />
          <div>
            <div className="showcase-recommendation-heading">
              <strong>{item.title}</strong>
              {item.amount_minor !== null ? (
                <span>{money(item.amount_minor, item.currency)}</span>
              ) : null}
            </div>
            <p>{item.explanation}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

function OverviewPage({
  data,
  month,
  onPage,
}: {
  data: ShowcaseData;
  month: string;
  onPage: (id: PageId) => void;
}) {
  const totalBalance = data.accounts.items.reduce(
    (sum, item) => sum + item.balance_minor,
    0,
  );
  return (
    <>
      <div className="showcase-overview-head">
        <div>
          <p className="showcase-kicker">个人金融工作台</p>
          <h1>账户总览</h1>
          <p className="showcase-subtitle">
            查看账户、近期收支和需要留意的事项。
          </p>
        </div>
        <div className="showcase-month-stamp">
          <span>账单周期</span>
          <strong>{month}</strong>
        </div>
      </div>
      <section aria-label="账户摘要" className="showcase-metric-grid">
        <Metric
          label="账户余额"
          value={money(totalBalance)}
          detail={`${data.accounts.items.length} 个模拟账户`}
          tone="accent"
        />
        <Metric
          label="本月收入"
          value={money(data.bills.income_minor, data.bills.currency)}
          detail={month}
        />
        <Metric
          label="本月支出"
          value={money(data.bills.expense_minor, data.bills.currency)}
          detail={month}
        />
        <Metric
          label="投资资产"
          value={money(
            data.portfolio.invested_value_minor,
            data.portfolio.currency,
          )}
          detail={`${data.portfolio.holdings.length} 项持仓`}
        />
      </section>
      <div className="showcase-home-grid">
        <section className="showcase-panel showcase-panel-wide">
          <SectionTitle
            title="收支概览"
            hint={`${month} · 基于模拟交易流水`}
            action={
              <button
                className="showcase-text-action"
                onClick={() => onPage("bills")}
                type="button"
              >
                查看账单
              </button>
            }
          />
          <div className="showcase-cashflow-line">
            <div>
              <span>收入</span>
              <strong>
                {money(data.bills.income_minor, data.bills.currency)}
              </strong>
            </div>
            <span className="showcase-cashflow-divider" />
            <div>
              <span>支出</span>
              <strong>
                {money(data.bills.expense_minor, data.bills.currency)}
              </strong>
            </div>
            <span className="showcase-cashflow-net">
              结余{" "}
              <b
                className={
                  data.bills.net_minor < 0
                    ? "showcase-negative"
                    : "showcase-positive"
                }
              >
                {money(data.bills.net_minor, data.bills.currency)}
              </b>
            </span>
          </div>
          <TransactionTable items={data.transactions.items} />
        </section>
        <section className="showcase-panel">
          <SectionTitle
            title="账单提示"
            hint="按确定性规则生成"
            action={
              <button
                className="showcase-text-action"
                onClick={() => onPage("bills")}
                type="button"
              >
                全部账单
              </button>
            }
          />
          <RecommendationList data={data.recommendations} />
          <p className="showcase-note">
            提示来自模拟流水规则，不构成欺诈判定或投资建议。
          </p>
        </section>
      </div>
      <section className="showcase-panel showcase-shortcuts">
        <SectionTitle title="常用场景" hint="通过对话查询或发起操作" />
        <div className="showcase-shortcut-grid">
          {pageItems.slice(2, 7).map((item) => (
            <button key={item.id} onClick={() => onPage(item.id)} type="button">
              <span>{item.number}</span>
              <strong>{item.label}</strong>
              <b aria-hidden="true">↗</b>
            </button>
          ))}
        </div>
      </section>
    </>
  );
}

function CardsPage({ data }: { data: ShowcaseData }) {
  return (
    <section className="showcase-panel">
      <SectionTitle title="银行卡" hint="状态以服务端返回为准" />
      <div className="showcase-card-grid">
        {data.cards.items.map((item) => (
          <CardTile item={item} key={item.id} />
        ))}
      </div>
      {!data.cards.items.length ? <EmptyState text="当前没有银行卡。" /> : null}
      <p className="showcase-note">
        可在智能助手中查询、冻结或解冻银行卡；状态变更需要服务端确认。
      </p>
    </section>
  );
}

function BillsPage({ data, month }: { data: ShowcaseData; month: string }) {
  const maxSpend = Math.max(
    ...data.bills.categories.map((item) => item.amount_minor),
    1,
  );
  return (
    <>
      <section className="showcase-metric-grid">
        <Metric
          label="收入"
          value={money(data.bills.income_minor, data.bills.currency)}
        />
        <Metric
          label="支出"
          value={money(data.bills.expense_minor, data.bills.currency)}
        />
        <Metric
          label="收支结余"
          value={money(data.bills.net_minor, data.bills.currency)}
          tone={data.bills.net_minor < 0 ? "plain" : "accent"}
        />
        <Metric
          label="规则提示"
          value={String(data.bills.anomalies.length)}
          detail="非欺诈判定"
        />
      </section>
      <section className="showcase-panel">
        <SectionTitle title="消费分类" hint={`${month} · 按金额排序`} />
        {data.bills.categories.length ? (
          <div className="showcase-category-list">
            {data.bills.categories.map((item) => (
              <div className="showcase-category" key={item.category}>
                <div>
                  <strong>{item.category}</strong>
                  <span>
                    {item.transaction_count} 笔 ·{" "}
                    {money(item.amount_minor, data.bills.currency)}
                  </span>
                </div>
                <div className="showcase-bar-track">
                  <span
                    style={{
                      width: `${Math.max(6, (item.amount_minor / maxSpend) * 100)}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState text="所选月份暂无支出分类。" />
        )}
      </section>
      <section className="showcase-panel">
        <SectionTitle title="收支趋势" hint="最近六个月的模拟流水汇总" />
        <div className="showcase-trend-grid">
          {data.bills.trends.map((item) => {
            const max = Math.max(item.income_minor, item.expense_minor, 1);
            return (
              <div className="showcase-trend" key={item.month}>
                <div className="showcase-trend-bars">
                  <span
                    className="trend-income"
                    style={{
                      height: `${Math.max(4, (item.income_minor / max) * 100)}%`,
                    }}
                  />
                  <span
                    className="trend-expense"
                    style={{
                      height: `${Math.max(4, (item.expense_minor / max) * 100)}%`,
                    }}
                  />
                </div>
                <small>{item.month.slice(5)}月</small>
              </div>
            );
          })}
        </div>
        <div className="showcase-legend">
          <span>
            <i className="trend-income" />
            收入
          </span>
          <span>
            <i className="trend-expense" />
            支出
          </span>
        </div>
      </section>
      <section className="showcase-panel">
        <SectionTitle
          title="交易明细"
          hint={`${data.transactions.total} 笔记录`}
        />
        <TransactionTable items={data.transactions.items} />
      </section>
      {data.bills.anomalies.length ? (
        <section className="showcase-panel">
          <SectionTitle
            title="需要核对的记录"
            hint="规则提示不代表已确认异常"
          />
          {data.bills.anomalies.map((item) => (
            <div className="showcase-anomaly-row" key={item.id}>
              <div>
                <strong>{item.merchant}</strong>
                <p>{item.anomaly_reason}</p>
              </div>
              <span>{money(item.amount_minor, item.currency)}</span>
            </div>
          ))}
        </section>
      ) : null}
    </>
  );
}

function SubscriptionsPage({ data }: { data: ShowcaseData }) {
  return (
    <>
      <section className="showcase-metric-grid">
        <Metric
          label="月度自动续费"
          value={money(
            data.subscriptions.monthly_total_minor,
            data.subscriptions.currency,
          )}
          tone="accent"
        />
        <Metric
          label="订阅数量"
          value={String(data.subscriptions.items.length)}
          detail="包含暂停和已取消项目"
        />
        <Metric
          label="启用中"
          value={String(
            data.subscriptions.items.filter((item) => item.status === "active")
              .length,
          )}
        />
      </section>
      <section className="showcase-panel">
        <SectionTitle title="订阅与代扣" hint="支持状态以服务端记录为准" />
        {data.subscriptions.items.length ? (
          <div className="showcase-list">
            {data.subscriptions.items.map((item) => (
              <div className="showcase-list-row" key={item.id}>
                <div className="showcase-row-mark">
                  {item.merchant.slice(0, 1)}
                </div>
                <div className="showcase-row-main">
                  <strong>{item.merchant}</strong>
                  <small>
                    下次扣款 {dateLabel(item.next_charge_at)} · 已识别{" "}
                    {item.detected_charge_count} 笔
                  </small>
                </div>
                <span className={`showcase-status status-${item.status}`}>
                  {statusName(item.status)}
                </span>
                <strong className="showcase-row-amount">
                  {money(item.amount_minor, item.currency)}
                  <small>/月</small>
                </strong>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState text="没有识别到周期性订阅。" />
        )}
        <p className="showcase-note">
          暂停、恢复或取消自动续费，请通过智能助手发起并核对确认信息。
        </p>
      </section>
    </>
  );
}

function TransfersPage({ data }: { data: ShowcaseData }) {
  return (
    <>
      <section className="showcase-panel">
        <SectionTitle title="账户与收款人" hint="仅显示当前模拟用户的数据" />
        <div className="showcase-two-column">
          <div>
            <h3 className="showcase-minor-heading">账户余额</h3>
            {data.accounts.items.map((item) => (
              <div className="showcase-simple-row" key={item.id}>
                <span>{item.label}</span>
                <strong>{money(item.balance_minor, item.currency)}</strong>
              </div>
            ))}
          </div>
          <div>
            <h3 className="showcase-minor-heading">已保存收款人</h3>
            {data.payees.items.length ? (
              data.payees.items.map((item) => (
                <div className="showcase-simple-row" key={item.id}>
                  <span>{item.display_name}</span>
                  <small>{item.destination_account_label}</small>
                </div>
              ))
            ) : (
              <EmptyState text="暂无收款人。" />
            )}
          </div>
        </div>
      </section>
      <section className="showcase-panel">
        <SectionTitle title="转账记录" hint="模拟转账及定时转账" />
        {data.transfers.items.length ? (
          <div className="showcase-list">
            {data.transfers.items.map((item) => (
              <div className="showcase-list-row" key={item.id}>
                <div className="showcase-row-mark">转</div>
                <div className="showcase-row-main">
                  <strong>{item.payee_name}</strong>
                  <small>
                    {item.source_account_label} ·{" "}
                    {item.transfer_type === "scheduled"
                      ? `计划 ${dateLabel(item.scheduled_at)}`
                      : "即时转账"}
                  </small>
                </div>
                <span className={`showcase-status status-${item.status}`}>
                  {statusName(item.status)}
                </span>
                <strong className="showcase-row-amount">
                  {money(item.amount_minor, item.currency)}
                </strong>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState text="暂无转账记录。" />
        )}
      </section>
      <section className="showcase-panel">
        <SectionTitle title="AA 分账" hint="模拟收付款进度" />
        {data.splits.items.length ? (
          data.splits.items.map((item) => (
            <div className="showcase-split" key={item.id}>
              <div>
                <strong>{item.title}</strong>
                <span>
                  {item.participant_count} 位参与人 · {statusName(item.status)}
                </span>
              </div>
              <b>{money(item.total_amount_minor, item.currency)}</b>
              <div className="showcase-split-participants">
                {item.participants.map((part) => (
                  <span key={part.id}>
                    {part.display_name} ·{" "}
                    {money(part.amount_minor, item.currency)} ·{" "}
                    {statusName(part.status)}
                  </span>
                ))}
              </div>
            </div>
          ))
        ) : (
          <EmptyState text="暂无分账记录。" />
        )}
      </section>
      <p className="showcase-note">
        所有写操作均通过智能助手任务确认；这里不提供绕过确认的直接转账入口。
      </p>
    </>
  );
}

function InvestmentsPage({ data }: { data: ShowcaseData }) {
  return (
    <>
      <section className="showcase-metric-grid">
        <Metric
          label="总资产"
          value={money(
            data.portfolio.total_assets_minor,
            data.portfolio.currency,
          )}
          tone="accent"
        />
        <Metric
          label="现金余额"
          value={money(
            data.portfolio.cash_balance_minor,
            data.portfolio.currency,
          )}
        />
        <Metric
          label="持仓估值"
          value={money(
            data.portfolio.invested_value_minor,
            data.portfolio.currency,
          )}
        />
        <Metric
          label="模拟浮动收益"
          value={money(
            data.portfolio.estimated_gain_minor,
            data.portfolio.currency,
          )}
          detail={`风险等级 ${data.risk.risk_level} · ${data.risk.risk_label}`}
        />
      </section>
      <section className="showcase-panel">
        <SectionTitle title="模拟持仓" hint="按演示净值估算" />
        {data.portfolio.holdings.length ? (
          <div className="showcase-list">
            {data.portfolio.holdings.map((item) => (
              <div className="showcase-list-row" key={item.id}>
                <div className="showcase-row-mark">理</div>
                <div className="showcase-row-main">
                  <strong>{item.product_name}</strong>
                  <small>
                    {item.units_micros.toLocaleString("zh-CN")} 份 · 成本{" "}
                    {money(item.purchase_price_minor, item.currency)}
                  </small>
                </div>
                <strong className="showcase-row-amount">
                  {money(item.current_value_minor, item.currency)}
                  <small
                    className={
                      item.estimated_gain_minor < 0
                        ? "showcase-negative"
                        : "showcase-positive"
                    }
                  >
                    {" "}
                    {money(item.estimated_gain_minor, item.currency)}
                  </small>
                </strong>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState text="当前没有持仓。" />
        )}
      </section>
      <section className="showcase-panel">
        <SectionTitle title="模拟产品" hint="展示产品风险等级与适当性结果" />
        {data.products.items.map((item) => (
          <div className="showcase-product-row" key={item.id}>
            <div>
              <strong>{item.name}</strong>
              <small>
                {item.category} · 风险 R{item.risk_level} · 起购{" "}
                {money(item.minimum_amount_minor, item.currency)}
              </small>
            </div>
            <span className={item.suitable ? "showcase-fit" : "showcase-unfit"}>
              {item.suitable ? "符合当前风险等级" : "超出当前风险等级"}
            </span>
          </div>
        ))}
      </section>
      <section className="showcase-panel">
        <SectionTitle title="操作记录" hint="申购和赎回订单" />
        {data.orders.items.length ? (
          data.orders.items.map((item) => (
            <div className="showcase-simple-row" key={item.id}>
              <span>
                {item.product_name} ·{" "}
                {item.order_type === "buy" ? "申购" : "赎回"}
              </span>
              <strong>
                {money(item.amount_minor, item.currency)} ·{" "}
                {statusName(item.status)}
              </strong>
            </div>
          ))
        ) : (
          <EmptyState text="暂无理财订单。" />
        )}
      </section>
      <p className="showcase-note">
        产品、净值和收益均为虚构模拟数据，不构成投资建议。
      </p>
    </>
  );
}

function ConfirmationPanel({
  confirmation,
  busy,
  onConfirm,
  onCancel,
}: {
  confirmation: Confirmation;
  busy: boolean;
  onConfirm: (verificationCode?: string) => void;
  onCancel: () => void;
}) {
  const [verificationCode, setVerificationCode] = useState("");
  const details = confirmation.details ?? {};
  const currency =
    typeof details.currency === "string" ? details.currency : "CNY";
  const readText = (key: string): string | null => {
    const value = details[key];
    return typeof value === "string" && value.trim() ? value : null;
  };
  const readAmount = (key: string): string | null =>
    typeof details[key] === "number"
      ? money(details[key] as number, currency)
      : null;
  const rows: Array<[string, string]> = [];
  const addText = (label: string, key: string) => {
    const value = readText(key);
    if (value) rows.push([label, value]);
  };
  const addAmount = (label: string, key: string) => {
    const value = readAmount(key);
    if (value) rows.push([label, value]);
  };

  if (confirmation.resource_type === "birthday_order") {
    const products = Array.isArray(details.items)
      ? details.items.flatMap((value) => {
          if (typeof value !== "object" || value === null) return [];
          const item = value as Record<string, unknown>;
          const name =
            typeof item.product_name === "string"
              ? item.product_name
              : typeof item.product_code === "string"
                ? item.product_code
                : "商品";
          const quantity =
            typeof item.quantity === "number" ? item.quantity : 1;
          return [`${name} × ${quantity}`];
        })
      : [];
    if (products.length) rows.push(["商品", products.join("、")]);
    addText("生日日期", "birthday_on");
    addText("预订日期", "scheduled_for");
    addAmount("订单金额", "amount_minor");
    addAmount("已预留预算", "held_minor");
    addText("付款账户", "account_label");
    addText("银行卡尾号", "card_suffix");
    addText("模拟商户", "merchant");
    addText("领取方式", "pickup_location");
  } else if (confirmation.resource_type === "birthday_plan") {
    const products = Array.isArray(details.items)
      ? details.items.flatMap((value) => {
          if (typeof value !== "object" || value === null) return [];
          const item = value as Record<string, unknown>;
          const name =
            typeof item.product_name === "string"
              ? item.product_name
              : typeof item.product_code === "string"
                ? item.product_code
                : "商品";
          const quantity =
            typeof item.quantity === "number" ? item.quantity : 1;
          return [name + " × " + quantity];
        })
      : [];
    if (products.length) rows.push(["预订商品", products.join("、")]);
    addText("生日日期", "birthday_on");
    addText("预订日期", "purchase_on");
    addAmount("当前预算", "current_budget_minor");
    addAmount(
      confirmation.target_status === "updated" ? "调整为" : "预算",
      confirmation.target_status === "updated"
        ? "proposed_budget_minor"
        : "budget_minor",
    );
    addAmount("商品参考总价", "catalog_total_minor");
    addText("付款账户", "account_label");
    addText("银行卡尾号", "card_suffix");
  } else if (confirmation.resource_type === "split") {
    addAmount("总金额", "total_amount_minor");
    const participants = Array.isArray(details.participants)
      ? details.participants.flatMap((value) => {
          if (typeof value !== "object" || value === null) return [];
          const person = value as Record<string, unknown>;
          if (typeof person.display_name !== "string") return [];
          const share =
            typeof person.amount_minor === "number"
              ? ` ${money(person.amount_minor, currency)}`
              : "";
          return [`${person.display_name}${share}`];
        })
      : [];
    if (participants.length) rows.push(["参与人", participants.join("、")]);
  } else if (confirmation.resource_type === "transfer") {
    addText("收款人", "payee_name");
    addAmount("转账金额", "amount_minor");
    addText("付款账户", "source_account_label");
    addText("备注", "remark");
    addText("执行日期", "scheduled_at");
  } else if (confirmation.resource_type === "investment_order") {
    addText("理财产品", "product_name");
    addAmount("操作金额", "amount_minor");
    addText("操作类型", "order_type");
    addText("付款账户", "account_label");
  } else if (confirmation.resource_type === "card") {
    addText("银行卡尾号", "card_suffix");
    addText("商品", "product_name");
    addAmount("消费金额", "amount_minor");
    addAmount("单笔限额", "single_limit_minor");
    addAmount("每日限额", "daily_limit_minor");
  } else if (confirmation.resource_type === "subscription") {
    addText("商户", "merchant");
    addAmount("周期金额", "amount_minor");
  }

  const operation =
    confirmation.tool_name === "card.report_lost"
      ? "挂失银行卡"
      : confirmation.tool_name === "card.replace"
        ? "补办银行卡"
        : confirmation.tool_name === "card.controls"
          ? "调整银行卡设置"
          : confirmation.tool_name === "card.purchase"
            ? "确认模拟消费"
            : confirmation.resource_type === "birthday_order"
              ? "确认生日礼品订单"
              : confirmation.resource_type === "birthday_plan"
                ? confirmation.target_status === "updated"
                  ? "调整生日预算"
                  : confirmation.target_status === "cancelled"
                    ? "取消生日计划"
                    : "预留生日预算"
                : confirmation.resource_type === "investment_order"
                  ? confirmation.tool_name === "investment.buy"
                    ? "确认模拟申购"
                    : "确认模拟赎回"
                  : confirmation.target_status === "frozen"
                    ? "冻结银行卡"
                    : confirmation.resource_type === "card" &&
                        confirmation.target_status === "active"
                      ? "解冻银行卡"
                      : confirmation.target_status === "active"
                        ? "恢复自动续费"
                        : confirmation.target_status === "paused"
                          ? "暂停自动续费"
                          : confirmation.target_status === "cancelled"
                            ? "取消自动续费"
                            : confirmation.target_status === "executed"
                              ? "确认资金操作"
                              : "确认操作";
  const requiresOtp = confirmation.confirmation_method === "demo_otp";
  const validOtp = /^[0-9]{6}$/.test(verificationCode);
  return (
    <section className="showcase-confirmation" aria-live="polite">
      <div>
        <span className="showcase-confirmation-label">需要你确认</span>
        <h3>{operation}</h3>
        <p>{confirmation.resource_label}</p>
      </div>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
        <div>
          <dt>执行前</dt>
          <dd>{statusName(confirmation.current_status)}</dd>
        </div>
        <div>
          <dt>执行后</dt>
          <dd>{statusName(confirmation.target_status)}</dd>
        </div>
        <div>
          <dt>有效期至</dt>
          <dd>{dateTimeLabel(confirmation.expires_at)}</dd>
        </div>
      </dl>
      {requiresOtp ? (
        <div className="showcase-verification">
          <label htmlFor="showcase-demo-verification">本地模拟验证码</label>
          <input
            autoComplete="off"
            id="showcase-demo-verification"
            inputMode="numeric"
            maxLength={6}
            onChange={(event) =>
              setVerificationCode(
                event.target.value.replace(/\D/g, "").slice(0, 6),
              )
            }
            pattern="[0-9]{6}"
            placeholder="输入 6 位验证码"
            value={verificationCode}
          />
          <small>
            在 API 本地终端运行{" "}
            <code>
              uv run --project apps/api python -m finorch_api.demo_verification
              --latest
            </code>{" "}
            获取。它只用于模拟强验证，不是短信或银行验证码。
          </small>
        </div>
      ) : null}
      <p className="showcase-note">
        {requiresOtp
          ? "这是高风险模拟操作。验证码与当前确认绑定，服务端会再次校验权限、参数和卡片状态。"
          : "确认后只执行此处显示的模拟操作。确认由服务端校验，页面不会直接改动业务状态。"}
      </p>
      <div className="showcase-button-row">
        <button
          className="showcase-button showcase-button-primary"
          disabled={busy || (requiresOtp && !validOtp)}
          onClick={() => onConfirm(requiresOtp ? verificationCode : undefined)}
          type="button"
        >
          确认操作
        </button>
        <button
          className="showcase-button"
          disabled={busy}
          onClick={onCancel}
          type="button"
        >
          取消
        </button>
      </div>
    </section>
  );
}

function resultDescription(
  toolName: string | null,
  data: Record<string, unknown> | null,
): string | null {
  if (!data) return null;
  if (toolName === "bill.monthly_summary") {
    const currency = typeof data.currency === "string" ? data.currency : "CNY";
    const totals = [
      typeof data.income_minor === "number"
        ? "收入 " + money(data.income_minor, currency)
        : null,
      typeof data.expense_minor === "number"
        ? "支出 " + money(data.expense_minor, currency)
        : null,
      typeof data.net_minor === "number"
        ? "结余 " + money(data.net_minor, currency)
        : null,
    ].filter((value): value is string => value !== null);
    const month = typeof data.month === "string" ? data.month : "月度账单";
    const anomalyCount = Array.isArray(data.anomalies)
      ? data.anomalies.length
      : 0;
    if (anomalyCount) totals.push(anomalyCount + " 条账单提示");
    return [month, ...totals].join(" · ");
  }
  if (toolName === "bill.annual_report") {
    const year =
      typeof data.year === "number" ? `${data.year} 年度` : "年度账单";
    const totals = [
      typeof data.income_minor === "number"
        ? `收入 ${money(data.income_minor, typeof data.currency === "string" ? data.currency : "CNY")}`
        : null,
      typeof data.expense_minor === "number"
        ? `支出 ${money(data.expense_minor, typeof data.currency === "string" ? data.currency : "CNY")}`
        : null,
      typeof data.net_minor === "number"
        ? `结余 ${money(data.net_minor, typeof data.currency === "string" ? data.currency : "CNY")}`
        : null,
    ].filter((value): value is string => value !== null);
    if (typeof data.top_expense_category === "string")
      totals.push(`主要支出：${data.top_expense_category}`);
    return [year, ...totals].join(" · ");
  }
  if (toolName === "subscription.reminders") {
    const reminders = Array.isArray(data.items)
      ? data.items.flatMap((value) => {
          if (typeof value !== "object" || value === null) return [];
          const item = value as Record<string, unknown>;
          if (typeof item.merchant !== "string") return [];
          const amount =
            typeof item.amount_minor === "number"
              ? ` ${money(item.amount_minor, typeof item.currency === "string" ? item.currency : "CNY")}`
              : "";
          const due =
            typeof item.next_charge_at === "string"
              ? ` · 下次扣款 ${dateLabel(item.next_charge_at)}`
              : "";
          return [`${item.merchant}${amount}${due}`];
        })
      : [];
    return reminders.length
      ? reminders.slice(0, 3).join("；")
      : "未来 30 天暂无续费提醒。";
  }
  const preferred = [
    "merchant",
    "product_name",
    "payee_name",
    "account_label",
    "status",
    "amount_minor",
    "balance_minor",
    "monthly_total_minor",
  ];
  const entries = preferred.flatMap((key) => {
    const value = data[key];
    if (value === undefined || value === null || typeof value === "object")
      return [];
    if (
      key === "status" &&
      ["succeeded", "running", "failed", "completed"].includes(String(value))
    ) {
      return [];
    }
    const label = labelMap[key] ?? key;
    const content =
      key === "status" && typeof value === "string"
        ? statusName(value)
        : key.endsWith("_minor") && typeof value === "number"
          ? money(value)
          : String(value);
    return [`${label}：${content}`];
  });
  const itemCount = Array.isArray(data.items) ? data.items.length : null;
  if (itemCount !== null) entries.push(`返回 ${itemCount} 项结果`);
  return entries.slice(0, 3).join(" · ") || null;
}

function AgentPanel({
  data,
  onRefreshData,
  initialPrompt,
  onPromptUsed,
}: {
  data: ShowcaseData;
  onRefreshData: () => void;
  initialPrompt?: string;
  onPromptUsed?: () => void;
}) {
  const [conversation] = useState(conversationId);
  const [task, setTask] = useState<AgentTaskResponse | null>(null);
  const [pendingCreate, setPendingCreate] = useState<PendingCreate | null>(
    null,
  );
  const [draft, setDraft] = useState(initialPrompt ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [audit, setAudit] = useState<AuditResponse | null>(null);
  const [showAudit, setShowAudit] = useState(false);

  useEffect(() => {
    let active = true;
    void apiClient
      .readRecentTask(conversation)
      .then((recent) => {
        if (active && recent) setTask(recent);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [conversation]);

  const updateTask = (value: AgentTaskResponse) => {
    setTask(value);
    setAudit(null);
    onRefreshData();
  };

  const send = async (text = draft) => {
    if (
      !text.trim() ||
      busy ||
      pendingCreate !== null ||
      task?.status === "awaiting_confirmation" ||
      task?.status === "running"
    )
      return;
    setBusy(true);
    setError("");
    try {
      let result: AgentTaskResponse;
      if (task?.status === "awaiting_input") {
        const body: TaskInputRequest = { request_text: text.trim() };
        result = await apiClient.provideTaskInput(task.id, body);
      } else {
        const body: CreateTaskRequest = {
          request_text: text.trim(),
          conversation_id: conversation,
        };
        const key = crypto.randomUUID();
        setPendingCreate({ key, body });
        result = await apiClient.createTask(body, key);
        setPendingCreate(null);
      }
      setDraft("");
      onPromptUsed?.();
      updateTask(result);
    } catch (reason) {
      setError(apiMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const lookUpPendingCreate = async () => {
    if (!pendingCreate || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiClient.readTaskByIdempotencyKey(
        pendingCreate.key,
        conversation,
        "create",
      );
      if (result) {
        setPendingCreate(null);
        onPromptUsed?.();
        updateTask(result);
      } else {
        setError("服务端暂未找到这次请求；可用同一请求键安全重试。");
      }
    } catch (reason) {
      setError(apiMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const retryPendingCreate = async () => {
    if (!pendingCreate || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiClient.createTask(
        pendingCreate.body,
        pendingCreate.key,
      );
      setPendingCreate(null);
      setDraft("");
      onPromptUsed?.();
      updateTask(result);
    } catch (reason) {
      setError(apiMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (verificationCode?: string) => {
    if (!task?.confirmation || busy) return;
    setBusy(true);
    setError("");
    try {
      const challenge = task.confirmation;
      updateTask(
        await apiClient.confirmTask(
          task.id,
          challenge.id,
          challenge.parameters_hash,
          challenge.idempotency_key,
          verificationCode,
        ),
      );
    } catch (reason) {
      setError(apiMessage(reason));
      void apiClient
        .readTask(task.id)
        .then(setTask)
        .catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!task || busy) return;
    setBusy(true);
    setError("");
    try {
      updateTask(await apiClient.cancelTask(task.id));
    } catch (reason) {
      setError(apiMessage(reason));
      void apiClient
        .readTask(task.id)
        .then(setTask)
        .catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  const loadTask = async () => {
    if (!task) return;
    setBusy(true);
    setError("");
    try {
      setTask(await apiClient.readTask(task.id));
    } catch (reason) {
      setError(apiMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const loadAudit = async () => {
    if (!task) return;
    if (showAudit) {
      setShowAudit(false);
      return;
    }
    setBusy(true);
    try {
      setAudit(await apiClient.readAudit(task.id));
      setShowAudit(true);
    } catch (reason) {
      setError(apiMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="showcase-agent-layout">
      <section className="showcase-panel showcase-agent-panel">
        <div className="showcase-agent-heading">
          <div>
            <p className="showcase-kicker">自然语言办理</p>
            <h2>你想处理什么？</h2>
          </div>
          <span
            className={`showcase-provider provider-${data.session.agent_provider}`}
          >
            {data.session.agent_provider === "fake" ? "演示模式" : "模型模式"}
          </span>
        </div>
        <p className="showcase-agent-intro">
          可查询账户、账单、银行卡、订阅和理财。所有业务操作均需在服务端确认。
        </p>
        <div aria-live="polite" className="showcase-task-stream">
          <div className="showcase-assistant-message">
            <span>{brand.name}</span>
            <p>你好，我可以帮你查看账户信息，或准备一项需要确认的业务操作。</p>
          </div>
          {task ? (
            <>
              <div className="showcase-user-message">
                <span>你的请求</span>
                <p>{task.request_text}</p>
              </div>
              <div className="showcase-assistant-message">
                <div className="showcase-assistant-status">
                  <span>任务状态</span>
                  <strong className={`showcase-status status-${task.status}`}>
                    {statusName(task.status)}
                  </strong>
                </div>
                <p>{task.message}</p>
              </div>
              {task.steps.map((step) => (
                <div
                  className={`showcase-step step-${step.status}`}
                  key={step.id}
                >
                  <div className="showcase-step-marker">
                    {step.status === "succeeded"
                      ? "✓"
                      : step.status === "failed"
                        ? "!"
                        : String(step.sequence).padStart(2, "0")}
                  </div>
                  <div>
                    <strong>{stepLabel(step)}</strong>
                    {step.error_code ? (
                      <p>
                        {errorLabelMap[step.error_code] ?? "该步骤未完成。"}
                      </p>
                    ) : null}
                    {resultDescription(step.tool_name, step.result_data) ? (
                      <small>
                        {resultDescription(step.tool_name, step.result_data)}
                      </small>
                    ) : null}
                  </div>
                  <span>{statusName(step.status)}</span>
                </div>
              ))}
            </>
          ) : null}
        </div>
        {task?.confirmation ? (
          <ConfirmationPanel
            key={task.confirmation.id}
            busy={busy}
            confirmation={task.confirmation}
            onCancel={() => void cancel()}
            onConfirm={(verificationCode) => void confirm(verificationCode)}
          />
        ) : null}
        {error ? (
          <div className="showcase-inline-error" role="alert">
            {error}
            {pendingCreate ? (
              <>
                <button
                  onClick={() => void lookUpPendingCreate()}
                  type="button"
                >
                  查询本次请求
                </button>
                <button onClick={() => void retryPendingCreate()} type="button">
                  使用同一请求键重试
                </button>
              </>
            ) : task ? (
              <button onClick={() => void loadTask()} type="button">
                重新读取任务
              </button>
            ) : null}
          </div>
        ) : null}
        <form
          className="showcase-composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <label className="showcase-sr-only" htmlFor="showcase-agent-request">
            输入办理请求
          </label>
          <textarea
            id="showcase-agent-request"
            disabled={
              busy ||
              pendingCreate !== null ||
              task?.status === "awaiting_confirmation" ||
              task?.status === "running"
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
                void send();
              }
            }}
            placeholder={
              task?.status === "awaiting_input"
                ? "补充任务所需信息"
                : "例如：查看本月账单，冻结尾号 1042 的卡"
            }
            value={draft}
          />
          <button
            className="showcase-button showcase-button-primary"
            disabled={!draft.trim() || busy || pendingCreate !== null}
            type="submit"
          >
            {busy
              ? "处理中…"
              : task?.status === "awaiting_input"
                ? "继续任务"
                : "发送请求"}
          </button>
        </form>
        <div className="showcase-composer-foot">
          <span>Enter 发送，Shift + Enter 换行</span>
          <div>
            {task &&
            !task.confirmation &&
            [
              "awaiting_input",
              "awaiting_confirmation",
              "planning",
              "running",
            ].includes(task.status) ? (
              <button
                disabled={busy}
                onClick={() => void cancel()}
                type="button"
              >
                取消任务
              </button>
            ) : null}
            <button
              disabled={!task || busy}
              onClick={() => void loadTask()}
              type="button"
            >
              刷新任务
            </button>
          </div>
        </div>
      </section>
      <aside className="showcase-agent-context">
        <section className="showcase-panel">
          <SectionTitle title="当前用户" />
          <strong>{data.session.display_name}</strong>
          <p>
            {data.session.environment === "development"
              ? "本地演示环境"
              : "测试环境"}{" "}
            · 合成数据
          </p>
          <small>身份由服务端模拟，不是登录凭证。</small>
        </section>
        <section className="showcase-panel">
          <SectionTitle
            title="银行卡"
            action={<span>{data.cards.items.length} 张</span>}
          />
          {data.cards.items.map((item) => (
            <div className="showcase-context-row" key={item.id}>
              <span>
                {item.label} · {item.card_suffix}
              </span>
              <strong>{statusName(item.status)}</strong>
            </div>
          ))}
        </section>
        <section className="showcase-panel">
          <SectionTitle
            title="最近操作"
            action={
              <button
                className="showcase-text-action"
                disabled={!task || busy}
                onClick={() => void loadAudit()}
                type="button"
              >
                {showAudit ? "收起" : "查看详情"}
              </button>
            }
          />
          {task ? (
            <>
              <p className="showcase-context-task">{task.message}</p>
              <small>{new Date(task.updated_at).toLocaleString("zh-CN")}</small>
            </>
          ) : (
            <EmptyState text="当前会话暂无任务。" />
          )}
          {showAudit && audit ? (
            <div className="showcase-audit-list">
              {audit.events.length ? (
                audit.events.map((event) => (
                  <div key={event.id}>
                    <strong>{auditEventLabel(event.event_type)}</strong>
                    <span>
                      {statusName(event.outcome)} ·{" "}
                      {new Date(event.occurred_at).toLocaleString("zh-CN")}
                    </span>
                  </div>
                ))
              ) : (
                <EmptyState text="当前任务暂无审计事件。" />
              )}
            </div>
          ) : null}
        </section>
      </aside>
    </div>
  );
}

function CrossScenePage({
  data,
  onStartTask,
}: {
  data: ShowcaseData;
  onStartTask: (prompt: string) => void;
}) {
  const [recipient, setRecipient] = useState(
    data.payees.items[0]?.display_name ?? "小林",
  );
  const [transfer, setTransfer] = useState("200.00");
  const [reserve, setReserve] = useState("3000.00");
  const [plan, setPlan] = useState<PaydayPlanPreviewResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const prompts = useMemo(
    () => [
      "帮我处理可疑扣款：查询异常账单和自动扣费，冻结相关银行卡并暂停对应代扣",
      "发薪日资金调度：给小林转 200 元，预留 3000 元，其余投资适合的产品",
    ],
    [],
  );
  const preview = async (event: FormEvent) => {
    event.preventDefault();
    const transferMinor = amountToMinor(transfer);
    const reserveMinor = amountToMinor(reserve);
    if (transferMinor === null || reserveMinor === null) {
      setError("请输入有效金额，最多保留两位小数。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body: PaydayPlanPreviewRequest = {
        recipient_name: recipient,
        transfer_amount_minor: transferMinor,
        reserve_amount_minor: reserveMinor,
        month: currentMonth(),
      };
      setPlan(await apiClient.previewPaydayPlan(body));
    } catch (reason) {
      setError(apiMessage(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <section className="showcase-panel">
        <SectionTitle
          title="跨场景任务"
          hint="任务会在确认节点暂停，确认后继续执行后续步骤"
        />
        <div className="showcase-demo-grid">
          {prompts.map((prompt, index) => (
            <article key={prompt}>
              <span>演示流程 0{index + 1}</span>
              <h3>{index === 0 ? "可疑扣款处置" : "发薪日资金调度"}</h3>
              <p>
                {index === 0
                  ? "查询账单提示与自动续费，核对依据后分步确认操作。"
                  : "读取余额和月度收支，预览转账、预留金额及理财预算。"}
              </p>
              <button
                className="showcase-button"
                onClick={() => onStartTask(prompt)}
                type="button"
              >
                在智能助手中开始
              </button>
            </article>
          ))}
        </div>
      </section>
      <section className="showcase-panel">
        <SectionTitle
          title="发薪日计划预览"
          hint="调整输入以比较不同分配结果；预览不会改变余额"
        />
        <form
          className="showcase-preview-form"
          onSubmit={(event) => void preview(event)}
        >
          <label>
            收款人
            <select
              onChange={(event) => setRecipient(event.target.value)}
              value={recipient}
            >
              {data.payees.items.map((item) => (
                <option key={item.id} value={item.display_name}>
                  {item.display_name} · {item.destination_account_label}
                </option>
              ))}
            </select>
          </label>
          <label>
            转账金额（元）
            <input
              inputMode="decimal"
              onChange={(event) => setTransfer(event.target.value)}
              value={transfer}
            />
          </label>
          <label>
            预留金额（元）
            <input
              inputMode="decimal"
              onChange={(event) => setReserve(event.target.value)}
              value={reserve}
            />
          </label>
          <button
            className="showcase-button showcase-button-primary"
            disabled={busy}
            type="submit"
          >
            {busy ? "计算中…" : "计算预览"}
          </button>
        </form>
        {error ? (
          <p className="showcase-inline-error" role="alert">
            {error}
          </p>
        ) : null}
        {plan ? (
          <div className="showcase-plan-result">
            <div className="showcase-plan-summary">
              <div>
                <span>付款账户</span>
                <strong>{plan.account_label}</strong>
              </div>
              <div>
                <span>当前余额</span>
                <strong>
                  {money(plan.account_balance_minor, plan.currency)}
                </strong>
              </div>
              <div>
                <span>本月收支</span>
                <strong>
                  收入 {money(plan.monthly_income_minor, plan.currency)} · 支出{" "}
                  {money(plan.monthly_expense_minor, plan.currency)}
                </strong>
              </div>
            </div>
            <div className="showcase-allocation-flow">
              <div>
                <span>向 {plan.recipient_name} 转账</span>
                <strong>
                  {money(plan.transfer_amount_minor, plan.currency)}
                </strong>
              </div>
              <b aria-hidden="true">−</b>
              <div>
                <span>转账后余额</span>
                <strong>
                  {money(plan.remaining_after_transfer_minor, plan.currency)}
                </strong>
              </div>
              <b aria-hidden="true">−</b>
              <div>
                <span>目标预留</span>
                <strong>
                  {money(plan.reserve_amount_minor, plan.currency)}
                </strong>
              </div>
              <b aria-hidden="true">=</b>
              <div
                className={
                  plan.reserve_shortfall_minor > 0
                    ? "showcase-negative"
                    : "showcase-positive"
                }
              >
                <span>可用于理财</span>
                <strong>
                  {money(plan.investment_budget_minor, plan.currency)}
                </strong>
              </div>
            </div>
            {plan.reserve_shortfall_minor > 0 ? (
              <p className="showcase-warning">
                按当前余额计算，预留目标还差{" "}
                {money(plan.reserve_shortfall_minor, plan.currency)}
                ；这只是模拟预览。
              </p>
            ) : null}
          </div>
        ) : null}
      </section>
      <section className="showcase-panel">
        <SectionTitle title="当前账单提示" hint="来自服务端确定性规则" />
        <RecommendationList data={data.recommendations} />
      </section>
    </>
  );
}

function renderScene(
  page: PageId,
  data: ShowcaseData,
  month: string,
  onPage: (id: PageId) => void,
  startTask: (prompt: string) => void,
) {
  if (page === "overview")
    return <OverviewPage data={data} month={month} onPage={onPage} />;
  if (page === "cards") return <CardsPage data={data} />;
  if (page === "bills") return <BillsPage data={data} month={month} />;
  if (page === "subscriptions") return <SubscriptionsPage data={data} />;
  if (page === "transfers") return <TransfersPage data={data} />;
  if (page === "investments") return <InvestmentsPage data={data} />;
  if (page === "cross-scene")
    return <CrossScenePage data={data} onStartTask={startTask} />;
  return <AgentPanel data={data} onRefreshData={() => undefined} />;
}

function initialPage(): PageId {
  const requested = window.location.hash.replace(/^#\/?/, "") as PageId;
  return pageItems.some((item) => item.id === requested)
    ? requested
    : "overview";
}

export default function Showcase() {
  const [page, setPage] = useState<PageId>(initialPage);
  const [month, setMonth] = useState(currentMonth);
  const { data, loading, error, refresh } = useShowcaseData(month);
  const [assistantPrompt, setAssistantPrompt] = useState("");
  const goToAssistant = (prompt: string) => {
    setAssistantPrompt(prompt);
    setPage("assistant");
  };
  const title = pageItems.find((item) => item.id === page)?.label ?? "账户总览";

  useEffect(() => {
    document.title = `${brand.name} · ${title}`;
    const pageHash = "#" + page;
    if (window.location.hash !== pageHash) {
      window.history.replaceState(
        window.history.state,
        "",
        window.location.pathname + pageHash,
      );
    }
  }, [page, title]);

  return (
    <div className="showcase-shell">
      <header className="showcase-topbar">
        <a
          aria-label={`${brand.name} 总览`}
          className="showcase-brand"
          href="/showcase"
          onClick={(event) => {
            event.preventDefault();
            setPage("overview");
          }}
        >
          <LogoMark />
          <span>
            <strong>{brand.name}</strong>
            <small>个人金融助手</small>
          </span>
        </a>
        <div className="showcase-topbar-status">
          <span className="showcase-demo-tag">演示环境</span>
          <details className="showcase-mode-details">
            <summary>
              {data?.session.agent_provider === "openai-compatible"
                ? "模型模式"
                : "规则演示"}
            </summary>
            <div>
              {data?.session.agent_provider === "openai-compatible"
                ? "当前请求由服务端转发至已配置的兼容模型；只使用合成演示数据。"
                : "当前使用确定性模拟规则，未调用外部模型。"}
            </div>
          </details>
          <span
            className={`showcase-api-dot ${data?.health.status === "ok" ? "is-online" : ""}`}
          />
          <span>
            {data?.health.status === "ok"
              ? "服务正常"
              : loading
                ? "连接中"
                : "服务不可用"}
          </span>
        </div>
        <button
          aria-label="刷新全部数据"
          className="showcase-refresh"
          disabled={loading}
          onClick={() => void refresh()}
          type="button"
        >
          刷新数据
        </button>
      </header>
      <div className="showcase-layout">
        <nav aria-label="主要导航" className="showcase-nav">
          <div className="showcase-nav-label">工作台</div>
          {pageItems.map((item) => (
            <button
              aria-current={page === item.id ? "page" : undefined}
              className={page === item.id ? "is-current" : ""}
              key={item.id}
              onClick={() => setPage(item.id)}
              type="button"
            >
              <span>{item.number}</span>
              <strong>{item.label}</strong>
              {item.id === "cross-scene" ? <i>演示</i> : null}
            </button>
          ))}
          <div className="showcase-nav-footer">
            <span className="showcase-avatar">
              {data?.session.display_name.slice(0, 1) ?? "F"}
            </span>
            <div>
              <strong>{data?.session.display_name ?? "模拟用户"}</strong>
              <small>本地合成数据</small>
            </div>
          </div>
        </nav>
        <main className="showcase-main">
          <div className="showcase-page-head">
            <div>
              <p className="showcase-breadcrumb">
                {brand.name} <span>/</span> {title}
              </p>
              {page === "overview" ? null : <h1>{title}</h1>}
            </div>
            <label className="showcase-month-select">
              账单月份
              <input
                aria-label="账单月份"
                onChange={(event) => setMonth(event.target.value)}
                type="month"
                value={month}
              />
            </label>
          </div>
          {error ? (
            <div className="showcase-load-error" role="alert">
              <span>{error}</span>
              <button onClick={() => void refresh()} type="button">
                重新加载
              </button>
            </div>
          ) : null}
          {loading && !data ? (
            <div className="showcase-loading" role="status">
              正在读取模拟账户…
            </div>
          ) : data ? (
            <>
              {page === "assistant" ? (
                <AgentPanel
                  data={data}
                  onRefreshData={() => void refresh()}
                  initialPrompt={assistantPrompt}
                  onPromptUsed={() => setAssistantPrompt("")}
                />
              ) : (
                renderScene(page, data, month, setPage, goToAssistant)
              )}
            </>
          ) : !loading ? (
            <div className="showcase-loading">
              当前无法显示账户数据，请检查 API 服务。
            </div>
          ) : null}
          <footer className="showcase-footer">
            所有账户、交易、产品及收益数据均为合成演示数据。没有连接真实银行或支付网络。
          </footer>
        </main>
      </div>
    </div>
  );
}
