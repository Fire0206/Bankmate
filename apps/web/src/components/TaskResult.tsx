import type { components } from "../generated/api";

type Task = components["schemas"]["AgentTaskResponse"];
type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function objectArray(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.filter(isObject) : [];
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value)
    ? value
    : null;
}

function formatAmount(value: unknown): string {
  const minor = numberValue(value);
  if (minor === null) return "金额暂不可显示";
  const absolute = Math.abs(minor);
  const whole = Math.floor(absolute / 100).toLocaleString("zh-CN");
  const fraction = String(absolute % 100).padStart(2, "0");
  return `${minor < 0 ? "−" : ""}¥${whole}.${fraction}`;
}

function dateLabel(value: unknown): string {
  if (typeof value !== "string") return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(parsed);
}

function statusLabel(value: unknown): string {
  const labels: Record<string, string> = {
    active: "正常续费",
    paused: "已暂停",
    cancelled: "已取消",
    frozen: "已冻结",
    awaiting_confirmation: "等待确认",
    scheduled: "待执行",
    executed: "已执行",
    open: "待收款",
    settled: "已结清",
  };
  const text = stringValue(value);
  return labels[text] ?? text;
}

function BillSummary({ data }: { data: JsonObject }) {
  const categories = objectArray(data.categories);
  const anomalies = objectArray(data.anomalies);
  const selectedCategory = stringValue(data.selected_category);
  const selectedTotal = numberValue(data.selected_category_expense_minor);
  const month = stringValue(data.month);

  return (
    <section aria-label="账单摘要" className="task-result">
      <div className="task-result-heading">
        <strong>{month} 账单</strong>
        {selectedCategory ? <span>{selectedCategory}支出</span> : null}
      </div>
      <div className="bill-total-row">
        <div>
          <span>{selectedCategory ? `${selectedCategory}支出` : "总支出"}</span>
          <strong>
            {selectedCategory && selectedTotal !== null
              ? formatAmount(selectedTotal)
              : formatAmount(data.expense_minor)}
          </strong>
        </div>
        <div>
          <span>收入</span>
          <strong>{formatAmount(data.income_minor)}</strong>
        </div>
        <div>
          <span>收支差额</span>
          <strong>{formatAmount(data.net_minor)}</strong>
        </div>
      </div>
      {categories.length ? (
        <div className="task-result-list">
          {categories.slice(0, 5).map((item) => (
            <div className="task-result-row" key={stringValue(item.category)}>
              <span>{stringValue(item.category)}</span>
              <strong>{formatAmount(item.amount_minor)}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {anomalies.length ? (
        <p className="task-result-notice">
          有 {anomalies.length} 笔交易符合演示提示规则；这不是欺诈结论。
        </p>
      ) : null}
    </section>
  );
}

function TransactionList({
  data,
  anomaliesOnly = false,
}: {
  data: JsonObject;
  anomaliesOnly?: boolean;
}) {
  const items = objectArray(data.items);
  const month = stringValue(data.month);
  return (
    <section
      aria-label={anomaliesOnly ? "异常交易" : "交易明细"}
      className={"task-result" + (anomaliesOnly ? " task-result-risky" : "")}
    >
      <div className="task-result-heading">
        <strong>{anomaliesOnly ? "异常提示" : `${month} 交易明细`}</strong>
        <span>{items.length} 笔</span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.slice(0, 8).map((item) => (
            <div
              className="task-result-row transaction-result-row"
              key={stringValue(item.id)}
            >
              <div>
                <strong>{stringValue(item.merchant)}</strong>
                <small>
                  {stringValue(item.category)} · {dateLabel(item.occurred_at)}
                </small>
                {anomaliesOnly && item.source_card_suffix ? (
                  <small>
                    银行卡尾号 {stringValue(item.source_card_suffix)}
                  </small>
                ) : null}
                {anomaliesOnly && item.anomaly_reason ? (
                  <small className="task-result-warning">
                    {stringValue(item.anomaly_reason)}
                  </small>
                ) : null}
              </div>
              <strong
                className={
                  item.direction === "income" ? "amount-income" : undefined
                }
              >
                {item.direction === "income" ? "+" : "−"}
                {formatAmount(item.amount_minor)}
              </strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">没有符合条件的交易。</p>
      )}
    </section>
  );
}

function SubscriptionList({ data }: { data: JsonObject }) {
  const items = objectArray(data.items);
  return (
    <section aria-label="订阅与代扣" className="task-result">
      <div className="task-result-heading">
        <strong>自动扣费</strong>
        <span>每月 {formatAmount(data.monthly_total_minor)}</span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.map((item) => (
            <div
              className="task-result-row transaction-result-row"
              key={stringValue(item.id)}
            >
              <div>
                <strong>{stringValue(item.merchant)}</strong>
                <small>
                  {statusLabel(item.status)} · 下次扣款{" "}
                  {dateLabel(item.next_charge_at)}
                </small>
              </div>
              <strong>{formatAmount(item.amount_minor)} / 月</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">暂未识别到周期扣费。</p>
      )}
    </section>
  );
}

function SubscriptionChange({ data }: { data: JsonObject }) {
  const subscription = isObject(data.subscription) ? data.subscription : null;
  if (!subscription) return null;
  const status = stringValue(subscription.status);
  const actionLabel: Record<string, string> = {
    active: "已恢复",
    paused: "已暂停",
    cancelled: "已取消",
  };
  return (
    <section
      aria-label="订阅状态更新"
      className="task-result task-result-success"
    >
      <strong>
        {stringValue(subscription.merchant)}自动续费
        {actionLabel[status] ?? statusLabel(status)}
      </strong>
      <span>月费 {formatAmount(subscription.amount_minor)}</span>
    </section>
  );
}

function AccountBalances({ data }: { data: JsonObject }) {
  const items = objectArray(data.items);
  return (
    <section aria-label="账户余额" className="task-result">
      <div className="task-result-heading">
        <strong>账户余额</strong>
        <span>{items.length} 个账户</span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.map((item) => (
            <div className="task-result-row" key={stringValue(item.id)}>
              <span>{stringValue(item.label)}</span>
              <strong>{formatAmount(item.balance_minor)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">暂时没有可用账户。</p>
      )}
    </section>
  );
}

function PayeeList({ data }: { data: JsonObject }) {
  const items = objectArray(data.items);
  return (
    <section aria-label="收款人" className="task-result">
      <div className="task-result-heading">
        <strong>已保存收款人</strong>
        <span>{items.length} 人</span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.map((item) => (
            <div className="task-result-row" key={stringValue(item.id)}>
              <span>{stringValue(item.display_name)}</span>
              <small>{stringValue(item.destination_account_label)}</small>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">暂无已保存收款人。</p>
      )}
    </section>
  );
}

function TransferList({ data }: { data: JsonObject }) {
  const items = objectArray(data.items);
  const labels: Record<string, string> = {
    awaiting_confirmation: "等待确认",
    scheduled: "待执行",
    executed: "已完成",
    cancelled: "已取消",
    failed: "失败",
  };
  return (
    <section aria-label="转账记录" className="task-result">
      <div className="task-result-heading">
        <strong>转账记录</strong>
        <span>{items.length} 笔</span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.slice(0, 8).map((item) => (
            <div
              className="task-result-row transaction-result-row"
              key={stringValue(item.id)}
            >
              <div>
                <strong>{stringValue(item.payee_name)}</strong>
                <small>
                  {labels[stringValue(item.status)] ?? stringValue(item.status)}
                  {item.transfer_type === "scheduled" ? " · 定时转账" : ""}
                  {item.scheduled_at
                    ? ` · ${dateLabel(item.scheduled_at)}`
                    : ""}
                </small>
              </div>
              <strong>{formatAmount(item.amount_minor)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">暂无转账记录。</p>
      )}
    </section>
  );
}

function TransferResult({ data }: { data: JsonObject }) {
  const transfer = isObject(data.transfer) ? data.transfer : data;
  const status = stringValue(transfer.status);
  const label: Record<string, string> = {
    executed: "转账已完成",
    scheduled: "定时转账已创建",
    cancelled: "定时转账已取消",
    failed: "转账未完成",
  };
  return (
    <section aria-label="转账结果" className="task-result task-result-success">
      <strong>{label[status] ?? "转账状态已更新"}</strong>
      <span>
        {stringValue(transfer.payee_name)} ·{" "}
        {formatAmount(transfer.amount_minor)}
      </span>
      {transfer.scheduled_at ? (
        <span>计划时间：{dateLabel(transfer.scheduled_at)}</span>
      ) : null}
    </section>
  );
}

function SplitList({ data }: { data: JsonObject }) {
  const items = objectArray(data.items);
  const labels: Record<string, string> = {
    awaiting_confirmation: "等待确认",
    open: "待收款",
    settled: "已结清",
    cancelled: "已取消",
  };
  return (
    <section aria-label="AA 分账" className="task-result">
      <div className="task-result-heading">
        <strong>AA 分账</strong>
        <span>{items.length} 笔</span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.slice(0, 8).map((item) => (
            <div
              className="task-result-row transaction-result-row"
              key={stringValue(item.id)}
            >
              <div>
                <strong>{stringValue(item.title)}</strong>
                <small>
                  {labels[stringValue(item.status)] ?? stringValue(item.status)}{" "}
                  · {numberValue(item.participant_count) ?? 0} 人
                </small>
              </div>
              <strong>{formatAmount(item.total_amount_minor)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">暂无 AA 分账。</p>
      )}
    </section>
  );
}

function SplitResult({ data }: { data: JsonObject }) {
  const participants = objectArray(data.participants);
  return (
    <section
      aria-label="AA 分账结果"
      className="task-result task-result-success"
    >
      <strong>
        {stringValue(data.status) === "succeeded"
          ? "AA 分账已更新"
          : "AA 分账结果"}
      </strong>
      <span>
        {stringValue(data.title)} · 总额 {formatAmount(data.total_amount_minor)}
      </span>
      {participants.length ? (
        <div className="task-result-list">
          {participants.map((item, index) => (
            <div
              className="task-result-row"
              key={
                stringValue(item.id) ||
                `${stringValue(item.display_name)}-${index}`
              }
            >
              <span>{stringValue(item.display_name)}</span>
              <strong>{formatAmount(item.amount_minor)}</strong>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function InvestmentProducts({ data }: { data: JsonObject }) {
  const items = objectArray(data.items);
  return (
    <section aria-label="模拟理财产品" className="task-result">
      <div className="task-result-heading">
        <strong>模拟理财产品</strong>
        <span>
          {stringValue(data.risk_label) ||
            `风险等级 R${String(data.risk_level ?? "—")}`}
        </span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.slice(0, 8).map((item) => (
            <div
              className="task-result-row transaction-result-row"
              key={stringValue(item.id)}
            >
              <div>
                <strong>{stringValue(item.name)}</strong>
                <small>
                  {stringValue(item.category)} · 风险 R
                  {String(item.risk_level ?? "—")} ·{" "}
                  {numberValue(item.annual_yield_bps) === null
                    ? "收益模拟"
                    : `年化参考 ${(numberValue(item.annual_yield_bps)! / 100).toFixed(2)}%`}
                </small>
                <small>
                  {item.suitable === true
                    ? "符合当前模拟风险等级"
                    : "超出当前模拟风险等级"}
                </small>
              </div>
              <strong>起购 {formatAmount(item.minimum_amount_minor)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">没有符合筛选条件的模拟产品。</p>
      )}
      <p className="task-result-notice">
        产品与收益均为模拟信息，不构成投资建议。
      </p>
    </section>
  );
}

function Portfolio({ data }: { data: JsonObject }) {
  const holdings = objectArray(data.holdings);
  return (
    <section aria-label="模拟理财持仓" className="task-result">
      <div className="task-result-heading">
        <strong>模拟资产</strong>
        <span>
          风险等级{" "}
          {stringValue(data.risk_label) || `R${String(data.risk_level ?? "—")}`}
        </span>
      </div>
      <div className="bill-total-row">
        <div>
          <span>现金</span>
          <strong>{formatAmount(data.cash_balance_minor)}</strong>
        </div>
        <div>
          <span>持仓</span>
          <strong>{formatAmount(data.invested_value_minor)}</strong>
        </div>
        <div>
          <span>资产合计</span>
          <strong>{formatAmount(data.total_assets_minor)}</strong>
        </div>
      </div>
      {holdings.length ? (
        <div className="task-result-list">
          {holdings.map((item) => (
            <div className="task-result-row" key={stringValue(item.id)}>
              <span>{stringValue(item.product_name)}</span>
              <strong>{formatAmount(item.current_value_minor)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">暂无模拟持仓。</p>
      )}
    </section>
  );
}

function InvestmentOrders({ data }: { data: JsonObject }) {
  const items = objectArray(data.items);
  const labels: Record<string, string> = {
    buy: "申购",
    redeem: "赎回",
    executed: "已完成",
    awaiting_confirmation: "等待确认",
    cancelled: "已取消",
    failed: "失败",
  };
  return (
    <section aria-label="理财操作记录" className="task-result">
      <div className="task-result-heading">
        <strong>理财操作记录</strong>
        <span>{items.length} 笔</span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.slice(0, 8).map((item) => (
            <div
              className="task-result-row transaction-result-row"
              key={stringValue(item.id)}
            >
              <div>
                <strong>{stringValue(item.product_name)}</strong>
                <small>
                  {labels[stringValue(item.order_type)] ?? "操作"} ·{" "}
                  {labels[stringValue(item.status)] ?? stringValue(item.status)}
                </small>
              </div>
              <strong>{formatAmount(item.amount_minor)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">暂无理财操作记录。</p>
      )}
    </section>
  );
}

function InvestmentResult({ data }: { data: JsonObject }) {
  const order = isObject(data.order) ? data.order : data;
  const action = stringValue(order.order_type) === "redeem" ? "赎回" : "申购";
  return (
    <section
      aria-label="理财操作结果"
      className="task-result task-result-success"
    >
      <strong>
        {stringValue(order.product_name)}已{action}
      </strong>
      <span>{formatAmount(order.amount_minor)} · 模拟订单已更新</span>
    </section>
  );
}

function PaydayPlan({ data }: { data: JsonObject }) {
  return (
    <section aria-label="发薪日资金安排" className="task-result">
      <div className="task-result-heading">
        <strong>发薪日资金安排</strong>
        <span>{stringValue(data.account_label)}</span>
      </div>
      <div className="task-result-list">
        <div className="task-result-row">
          <span>当前余额</span>
          <strong>{formatAmount(data.account_balance_minor)}</strong>
        </div>
        <div className="task-result-row">
          <span>{stringValue(data.month)} 收入 / 支出</span>
          <strong>
            {formatAmount(data.monthly_income_minor)} /{" "}
            {formatAmount(data.monthly_expense_minor)}
          </strong>
        </div>
        <div className="task-result-row">
          <span>转给{stringValue(data.recipient_name)}</span>
          <strong>{formatAmount(data.transfer_amount_minor)}</strong>
        </div>
        <div className="task-result-row">
          <span>保留金额</span>
          <strong>{formatAmount(data.reserve_amount_minor)}</strong>
        </div>
        <div className="task-result-row">
          <span>可投资额度</span>
          <strong>{formatAmount(data.investment_budget_minor)}</strong>
        </div>
      </div>
      <p className="task-result-notice">
        这是基于模拟数据计算的安排，资金操作仍需逐项确认。
      </p>
    </section>
  );
}

function resultForTool(toolName: string, data: JsonObject) {
  switch (toolName) {
    case "transfer.accounts":
      return <AccountBalances data={data} />;
    case "transfer.payees":
      return <PayeeList data={data} />;
    case "transfer.history":
      return <TransferList data={data} />;
    case "transfer.simulate_due":
      return <TransferList data={data} />;
    case "transfer.create":
    case "transfer.schedule":
    case "transfer.cancel_scheduled":
      return <TransferResult data={data} />;
    case "transfer.splits":
      return <SplitList data={data} />;
    case "transfer.split_create":
    case "transfer.split_collect":
      return <SplitResult data={data} />;
    case "investment.products":
    case "investment.compare":
      return <InvestmentProducts data={data} />;
    case "investment.portfolio":
      return <Portfolio data={data} />;
    case "investment.orders":
      return <InvestmentOrders data={data} />;
    case "investment.buy":
    case "investment.redeem":
      return <InvestmentResult data={data} />;
    case "finance.payday_plan":
      return <PaydayPlan data={data} />;
    case "bill.monthly_summary":
      return <BillSummary data={data} />;
    case "bill.transactions":
      return <TransactionList data={data} />;
    case "bill.anomalies":
      return <TransactionList anomaliesOnly data={data} />;
    case "subscription.list":
      return <SubscriptionList data={data} />;
    case "subscription.pause":
    case "subscription.resume":
    case "subscription.cancel":
      return <SubscriptionChange data={data} />;
    default:
      return null;
  }
}

export function TaskResult({ task }: { task: Task }) {
  const latestByTool = new Map<string, Task["steps"][number]>();
  for (const step of task.steps) {
    if (
      step.status === "succeeded" &&
      step.tool_name &&
      isObject(step.result_data)
    )
      latestByTool.set(step.tool_name, step);
  }
  const allResults = [...latestByTool.values()].sort(
    (a, b) => a.sequence - b.sequence,
  );
  const hasSubscriptionChange = allResults.some((step) =>
    [
      "subscription.pause",
      "subscription.resume",
      "subscription.cancel",
    ].includes(step.tool_name ?? ""),
  );
  const results = hasSubscriptionChange
    ? allResults.filter((step) => step.tool_name !== "subscription.list")
    : allResults;
  if (!results.length) return null;

  return (
    <div className="task-result-stack">
      {results.map((step) => (
        <div key={step.id}>
          {step.tool_name && isObject(step.result_data)
            ? resultForTool(step.tool_name, step.result_data)
            : null}
        </div>
      ))}
    </div>
  );
}
