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
          有 {anomalies.length} 笔支出符合金额提示规则，可查看交易明细。
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
      className="task-result"
    >
      <div className="task-result-heading">
        <strong>{anomaliesOnly ? "金额提示" : `${month} 交易明细`}</strong>
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

export function TaskResult({ task }: { task: Task }) {
  const completedTool = [...task.steps]
    .reverse()
    .find(
      (step) =>
        step.status === "succeeded" && step.tool_name && step.result_data,
    );
  if (
    !completedTool ||
    !completedTool.tool_name ||
    !isObject(completedTool.result_data)
  )
    return null;

  const data = completedTool.result_data;
  switch (completedTool.tool_name) {
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
