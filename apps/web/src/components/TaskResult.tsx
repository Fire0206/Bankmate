import { useState } from "react";

import type { components } from "../generated/api";
import { apiClient } from "../api/client";
import { AppIcon } from "./AppIcon";
import { MerchantMark } from "./MerchantMark";
import { cardLabel } from "./cardFormat";
import { RiskAssessmentForm } from "./RiskAssessmentForm";
import { customerText } from "../userFacing";

type Task = components["schemas"]["AgentTaskResponse"];
type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function objectArray(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.filter(isObject) : [];
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? customerText(value) : "";
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
    lost: "已挂失",
    replaced: "已补卡停用",
    awaiting_confirmation: "等待确认",
    scheduled: "待执行",
    executed: "已执行",
    open: "待收款",
    settled: "已结清",
  };
  const text = stringValue(value);
  return labels[text] ?? "状态待更新";
}

function CardResults({ data }: { data: JsonObject }) {
  const card = isObject(data.card) ? data.card : null;
  const items = card ? [card] : objectArray(data.items);
  return (
    <section aria-label="银行卡查询结果" className="task-result">
      <div className="task-result-heading">
        <strong>银行卡</strong>
        <span>{items.length} 张</span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.map((item, index) => (
            <div
              className="task-result-row"
              key={stringValue(item.id) || index}
            >
              <span>
                {cardLabel(stringValue(item.label))} · 尾号{" "}
                {stringValue(item.card_suffix)}
              </span>
              <strong>{statusLabel(item.status)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">当前没有银行卡。</p>
      )}
    </section>
  );
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
          有 {anomalies.length} 笔交易符合消费提醒规则，请核对是否为本人消费。
        </p>
      ) : null}
    </section>
  );
}

function AnnualBill({ data }: { data: JsonObject }) {
  const months = objectArray(data.monthly_totals);
  const categories = objectArray(data.categories);
  const anomalies = objectArray(data.anomalies);
  return (
    <section aria-label="年度账单" className="task-result">
      <div className="task-result-heading">
        <strong>{stringValue(data.year)} 年度账单</strong>
      </div>
      <div className="bill-total-row">
        <div>
          <span>总收入</span>
          <strong>{formatAmount(data.income_minor)}</strong>
        </div>
        <div>
          <span>总支出</span>
          <strong>{formatAmount(data.expense_minor)}</strong>
        </div>
        <div>
          <span>收支差额</span>
          <strong>{formatAmount(data.net_minor)}</strong>
        </div>
      </div>
      {data.top_expense_category ? (
        <p>主要支出类别：{stringValue(data.top_expense_category)}</p>
      ) : null}
      <div className="task-result-list">
        {months.map((item) => (
          <div className="task-result-row" key={stringValue(item.month)}>
            <span>{stringValue(item.month)}</span>
            <span>
              收入 {formatAmount(item.income_minor)} · 支出{" "}
              {formatAmount(item.expense_minor)}
            </span>
          </div>
        ))}
      </div>
      {categories.length ? (
        <p>
          支出分类：
          {categories
            .map(
              (item) =>
                `${stringValue(item.category)} ${formatAmount(item.amount_minor)}`,
            )
            .join("、")}
        </p>
      ) : null}
      {anomalies.length ? (
        <p className="task-result-notice">
          {anomalies.length} 笔交易符合消费提醒规则，请核对是否为本人消费。
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
              <MerchantMark
                category={stringValue(item.category)}
                merchant={stringValue(item.merchant)}
              />
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
  const [drafts, setDrafts] = useState<Record<string, number>>({});
  const [saved, setSaved] = useState<
    Record<string, { days: number; version: number }>
  >({});
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function saveReminder(item: JsonObject) {
    const id = stringValue(item.id);
    const days = drafts[id] ?? numberValue(item.reminder_days_before);
    const version = saved[id]?.version ?? numberValue(item.version);
    if (!id || days === null || version === null) return;
    setWorking(id);
    setError(null);
    try {
      const response = await apiClient.setSubscriptionReminder(id, {
        days_before: days,
        expected_version: version,
      });
      setSaved((previous) => ({
        ...previous,
        [id]: {
          days: response.reminder_days_before,
          version: response.version,
        },
      }));
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "提醒设置未保存，请刷新后重试。",
      );
    } finally {
      setWorking(null);
    }
  }
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
                <div className="reminder-preference">
                  <label htmlFor={"reminder-" + stringValue(item.id)}>
                    提前提醒
                  </label>
                  <select
                    id={"reminder-" + stringValue(item.id)}
                    value={
                      drafts[stringValue(item.id)] ??
                      saved[stringValue(item.id)]?.days ??
                      numberValue(item.reminder_days_before) ??
                      3
                    }
                    onChange={(event) =>
                      setDrafts((previous) => ({
                        ...previous,
                        [stringValue(item.id)]: Number(event.target.value),
                      }))
                    }
                  >
                    {[0, 1, 3, 7, 14, 30].map((days) => (
                      <option key={days} value={days}>
                        {days} 天
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    disabled={working === stringValue(item.id)}
                    onClick={() => void saveReminder(item)}
                  >
                    {working === stringValue(item.id) ? "保存中" : "保存"}
                  </button>
                </div>
              </div>
              <strong>{formatAmount(item.amount_minor)} / 月</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">暂未识别到周期扣费。</p>
      )}
      {error ? (
        <p role="alert" className="task-result-notice">
          {error}
        </p>
      ) : null}
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

function SubscriptionReminders({ data }: { data: JsonObject }) {
  const [items, setItems] = useState(objectArray(data.items));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function checkDueReminders() {
    setBusy(true);
    setError(null);
    try {
      await apiClient.refreshSubscriptionReminders();
      setItems(
        objectArray((await apiClient.readSubscriptionReminders()).items),
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "提醒检查失败，请重试。",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="续费提醒" className="task-result">
      <div className="task-result-heading">
        <strong>续费提醒</strong>
        <span>{items.length} 项即将续费</span>
      </div>
      <button
        type="button"
        className="reminder-refresh"
        disabled={busy}
        onClick={() => void checkDueReminders()}
      >
        {busy ? "检查中" : "检查到期提醒"}
      </button>
      {items.length ? (
        <div className="task-result-list">
          {items.map((item) => (
            <div
              className="task-result-row"
              key={stringValue(item.subscription_id)}
            >
              <div>
                <strong>{stringValue(item.merchant)}</strong>
                <small>
                  下次扣款 {dateLabel(item.next_charge_at)} · 提前{" "}
                  {numberValue(item.reminder_days_before) ?? 3} 天提醒
                  {item.delivered === true ? " · 已生成应用内提醒" : ""}
                </small>
              </div>
              <strong>{formatAmount(item.amount_minor)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">未来 30 天没有即将续费的项目。</p>
      )}
      {error ? (
        <p role="alert" className="task-result-notice">
          {error}
        </p>
      ) : null}
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
              <small>
                {stringValue(item.destination_account_label)}
                {item.phone_masked
                  ? ` · ${stringValue(item.phone_masked)}`
                  : ""}
              </small>
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
                {item.remark ? (
                  <small>备注：{stringValue(item.remark)}</small>
                ) : null}
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
      {transfer.remark ? (
        <span>备注：{stringValue(transfer.remark)}</span>
      ) : null}
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
    <section aria-label="理财产品" className="task-result">
      <div className="task-result-heading">
        <strong>理财产品</strong>
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
                    ? "浮动估值"
                    : `年化参考 ${(numberValue(item.annual_yield_bps)! / 100).toFixed(2)}%`}
                </small>
                <small>
                  {item.suitable === true
                    ? "符合当前风险等级"
                    : "超出当前风险等级"}
                </small>
              </div>
              <strong>起购 {formatAmount(item.minimum_amount_minor)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">没有找到符合筛选条件的产品。</p>
      )}
      <p className="task-result-notice">
        产品与收益为虚拟信息，不构成投资建议。
      </p>
    </section>
  );
}

function Portfolio({ data }: { data: JsonObject }) {
  const holdings = objectArray(data.holdings);
  return (
    <section aria-label="理财持仓" className="task-result">
      <div className="task-result-heading">
        <strong>资产</strong>
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
        <p className="task-result-empty">暂无持仓。</p>
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
      <span>{formatAmount(order.amount_minor)} · 订单状态已更新</span>
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
          <span>规划时余额</span>
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
        资金安排根据账户数据计算，涉及变更的操作仍需逐项确认。
      </p>
    </section>
  );
}

function BirthdayPlans({ data }: { data: JsonObject }) {
  const items = typeof data.id === "string" ? [data] : objectArray(data.items);
  const stateName: Record<string, string> = {
    scheduled: "已预约",
    awaiting_confirmation: "等待购买确认",
    paid: "已支付",
    completed: "已完成",
    cancelled: "已取消",
    failed: "执行失败",
  };
  return (
    <section aria-label="生日预算计划" className="task-result">
      <div className="task-result-heading">
        <strong>生日预算与提醒</strong>
        <span>{items.length} 项</span>
      </div>
      {items.length ? (
        <div className="task-result-list">
          {items.map((item, index) => (
            <div
              className="task-result-row"
              key={stringValue(item.id) || index}
            >
              <span>
                生日 {dateLabel(item.birthday_on)} · 预订{" "}
                {dateLabel(item.purchase_on)}
              </span>
              <strong>{formatAmount(item.budget_minor)}</strong>
              <small>
                {stateName[stringValue(item.order_status)] ||
                  stateName[stringValue(item.status)] ||
                  "计划状态待更新"}
                {item.funds_held === true
                  ? ` · 已预留 ${formatAmount(item.held_minor)}`
                  : " · 无资金预留"}
                {item.card_suffix
                  ? ` · 银行卡尾号 ${stringValue(item.card_suffix)}`
                  : ""}
              </small>
              {item.due_for_confirmation === true ? (
                <small>商品已到预订日期；确认前不会扣款。</small>
              ) : null}
              {objectArray(item.items).length ? (
                <small>
                  商品：
                  {objectArray(item.items)
                    .map(
                      (product) =>
                        `${stringValue(product.product_name)} × ${String(product.quantity ?? 1)}`,
                    )
                    .join("、")}
                </small>
              ) : null}
              {isObject(item.order) && item.order.status === "paid" ? (
                <small>
                  {formatAmount(item.order.total_amount_minor)} · 已记入账户流水
                </small>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="task-result-empty">暂无已确认的生日预算计划。</p>
      )}
    </section>
  );
}

function resultForTool(toolName: string, data: JsonObject) {
  switch (toolName) {
    case "card.list":
    case "card.get":
      return <CardResults data={data} />;
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
    case "birthday.list":
    case "birthday.plan":
    case "birthday.order":
    case "birthday.budget_update":
    case "birthday.cancel":
      return <BirthdayPlans data={data} />;
    case "bill.monthly_summary":
      return <BillSummary data={data} />;
    case "bill.annual_report":
      return <AnnualBill data={data} />;
    case "bill.transactions":
      return <TransactionList data={data} />;
    case "bill.anomalies":
      return <TransactionList anomaliesOnly data={data} />;
    case "subscription.list":
      return <SubscriptionList data={data} />;
    case "subscription.reminders":
      return <SubscriptionReminders data={data} />;
    case "subscription.pause":
    case "subscription.resume":
    case "subscription.cancel":
      return <SubscriptionChange data={data} />;
    default:
      return null;
  }
}

type Step = Task["steps"][number];

const resultTitles: Record<string, string> = {
  "card.list": "银行卡",
  "card.get": "银行卡状态",
  "card.applications": "银行卡申请",
  "bill.monthly_summary": "月度账单",
  "bill.annual_report": "年度账单",
  "bill.transactions": "交易明细",
  "bill.anomalies": "异常消费提示",
  "subscription.list": "自动扣费",
  "subscription.reminders": "续费提醒",
  "transfer.accounts": "账户余额",
  "transfer.payees": "收款人",
  "transfer.history": "转账记录",
  "transfer.simulate_due": "到期转账",
  "transfer.splits": "AA 分账",
  "investment.products": "理财产品",
  "investment.compare": "理财产品比较",
  "investment.profile": "风险等级",
  "investment.assessment_questions": "风险测评",
  "investment.portfolio": "理财持仓",
  "investment.orders": "理财操作记录",
  "finance.payday_plan": "发薪日资金安排",
  "birthday.list": "生日预算与预订",
};

const writeTitles: Record<string, string> = {
  "card.freeze": "银行卡已冻结",
  "card.unfreeze": "银行卡已解冻",
  "card.report_lost": "银行卡已挂失",
  "card.replace": "补卡申请已记录",
  "card.apply": "借记卡申请已记录",
  "card.controls": "银行卡消费设置已更新",
  "card.purchase": "商品已记入账户",
  "subscription.pause": "自动续费已暂停",
  "subscription.resume": "自动续费已恢复",
  "subscription.cancel": "自动续费已取消",
  "transfer.create": "转账已记账",
  "transfer.schedule": "定时转账已创建",
  "transfer.cancel_scheduled": "定时转账已取消",
  "transfer.split_create": "AA 分账已创建",
  "transfer.split_collect": "AA 收款已记账",
  "investment.buy": "申购已记账",
  "investment.redeem": "赎回已记账",
  "birthday.plan": "生日预算已预留",
  "birthday.order": "生日礼品订单已记账",
  "birthday.budget_update": "生日预算已更新",
  "birthday.cancel": "生日计划已取消",
};

function isObjectResult(
  step: Step,
): step is Step & { result_data: JsonObject } {
  return isObject(step.result_data);
}

function readIntentScore(toolName: string, request: string): number {
  if (toolName === "investment.compare" && /比较|对比|区别|哪款/.test(request))
    return 2;
  if (toolName === "bill.anomalies" && /异常|可疑|重复扣费/.test(request))
    return 2;
  if (toolName === "bill.annual_report" && /年度|全年/.test(request)) return 2;
  if (
    toolName === "subscription.reminders" &&
    /提醒|即将续费|下次扣款/.test(request)
  )
    return 2;
  if (toolName === "bill.transactions" && /流水|明细|交易/.test(request))
    return 2;
  if (
    toolName === "finance.payday_plan" &&
    /发薪|资金安排|资金规划/.test(request)
  )
    return 2;
  return 0;
}

function conciseValue(step: Step): string[] {
  if (!isObjectResult(step) || !step.tool_name) return [];
  const data = step.result_data;
  const items = objectArray(data.items);

  switch (step.tool_name) {
    case "card.list":
      return items
        .slice(0, 2)
        .map(
          (item) =>
            `${cardLabel(stringValue(item.label))} · 尾号 ${stringValue(item.card_suffix)} · ${statusLabel(item.status)}`,
        );
    case "card.get": {
      const card = isObject(data.card) ? data.card : data;
      return [
        `${cardLabel(stringValue(card.label))} · 尾号 ${stringValue(card.card_suffix)} · ${statusLabel(card.status)}`,
      ];
    }
    case "card.applications":
      return items.length
        ? items.slice(0, 3).map((item) => {
            const status =
              {
                pending_confirmation: "待确认",
                submitted: "待处理",
                approved: "已通过",
                rejected: "未通过",
                cancelled: "已取消",
              }[stringValue(item.status)] ?? "状态待更新";
            return `${stringValue(item.label)} · ${status}${item.issued_card_suffix ? ` · 新卡尾号 ${stringValue(item.issued_card_suffix)}` : ""}`;
          })
        : ["暂无银行卡申请"];
    case "bill.monthly_summary": {
      const categories = objectArray(data.categories);
      return [
        `${stringValue(data.month)}支出 ${formatAmount(data.expense_minor)} · 收入 ${formatAmount(data.income_minor)}`,
        ...categories
          .slice(0, 2)
          .map(
            (item) =>
              `${stringValue(item.category)} ${formatAmount(item.amount_minor)}`,
          ),
      ];
    }
    case "bill.annual_report":
      return [
        `${stringValue(data.year)} 年支出 ${formatAmount(data.expense_minor)} · 收入 ${formatAmount(data.income_minor)}`,
        data.top_expense_category
          ? `主要支出：${stringValue(data.top_expense_category)}`
          : "本年暂无支出",
      ];
    case "bill.anomalies":
      return items.length
        ? items
            .slice(0, 2)
            .map(
              (item) =>
                `${stringValue(item.merchant)} · ${formatAmount(item.amount_minor)} · ${stringValue(item.anomaly_reason)}`,
            )
        : ["没有发现符合提示规则的交易。"];
    case "bill.transactions":
      return items.length
        ? items
            .slice(0, 3)
            .map(
              (item) =>
                `${stringValue(item.merchant)} · ${formatAmount(item.amount_minor)}`,
            )
        : ["没有符合条件的交易。"];
    case "subscription.list":
      return [
        `${items.length} 项自动扣费 · 每月合计 ${formatAmount(data.monthly_total_minor)}`,
        ...items
          .slice(0, 2)
          .map(
            (item) =>
              `${stringValue(item.merchant)} · ${formatAmount(item.amount_minor)} / 月`,
          ),
      ];
    case "subscription.reminders":
      return items.length
        ? items
            .slice(0, 2)
            .map(
              (item) =>
                stringValue(item.merchant) +
                " · " +
                dateLabel(item.next_charge_at) +
                " · " +
                formatAmount(item.amount_minor),
            )
        : ["未来 30 天没有即将续费的项目。"];
    case "transfer.accounts":
      return items
        .slice(0, 3)
        .map(
          (item) =>
            `${stringValue(item.label)} · ${formatAmount(item.balance_minor)}`,
        );
    case "transfer.payees":
      return [`${items.length} 位已保存收款人`];
    case "transfer.history":
      return [`${items.length} 笔转账记录`];
    case "transfer.splits":
      return [`${items.length} 笔 AA 分账`];
    case "investment.products":
    case "investment.compare": {
      const suitable = items.filter((item) => item.suitable === true);
      return suitable.length
        ? suitable
            .slice(0, 3)
            .map(
              (item) =>
                `${stringValue(item.name)} · 风险 R${String(item.risk_level ?? "—")}`,
            )
        : ["没有找到符合当前风险等级的产品。"];
    }
    case "investment.profile":
      return [
        stringValue(data.risk_label) ||
          `风险等级 R${String(data.risk_level ?? "—")}`,
      ];
    case "investment.portfolio":
      return [
        `资产合计 ${formatAmount(data.total_assets_minor)} · 持仓 ${formatAmount(data.invested_value_minor)}`,
      ];
    case "investment.orders":
      return [`${items.length} 笔理财操作记录`];
    case "finance.payday_plan":
      return [
        `规划时余额 ${formatAmount(data.account_balance_minor)}`,
        `月收入 ${formatAmount(data.monthly_income_minor)} · 月支出 ${formatAmount(data.monthly_expense_minor)}`,
        `转账 ${formatAmount(data.transfer_amount_minor)} · 保留 ${formatAmount(data.reserve_amount_minor)} · 可投资 ${formatAmount(data.investment_budget_minor)}`,
      ];
    case "birthday.list":
      return items.length
        ? items
            .slice(0, 2)
            .map(
              (item) =>
                `${stringValue(item.birthday_on)} 生日 · 预算 ${formatAmount(item.budget_minor)} · ${item.funds_held === true ? "资金已预留" : "无资金预留"} · ${statusLabel(item.order_status ?? item.status)}`,
            )
        : ["暂无生日预算计划。"];
    default:
      return [];
  }
}

function writeSummary(step: Step): { title: string; detail: string } {
  const toolName = step.tool_name ?? "";
  const data = isObjectResult(step) ? step.result_data : {};
  if (toolName.startsWith("birthday.")) {
    const order = isObject(data.order) ? data.order : {};
    return {
      title: writeTitles[toolName] ?? "生日计划已更新",
      detail: [
        `${stringValue(data.birthday_on)} 生日`,
        `预算 ${formatAmount(data.budget_minor)}`,
        data.funds_held === true
          ? `预留 ${formatAmount(data.held_minor)}`
          : "无预留资金",
        order.status === "paid"
          ? `订单 ${formatAmount(order.total_amount_minor)} 已支付`
          : null,
      ]
        .filter(Boolean)
        .join(" · "),
    };
  }
  if (toolName.startsWith("card.")) {
    if (toolName === "card.purchase") {
      return {
        title: writeTitles[toolName],
        detail: `${stringValue(data.product_name)} · ${formatAmount(data.amount_minor)} · 尾号 ${stringValue(data.card_suffix)}`,
      };
    }
    if (toolName === "card.controls") {
      return {
        title: writeTitles[toolName],
        detail: `尾号 ${stringValue(data.card_suffix)} · 单笔 ${formatAmount((isObject(data.card) ? data.card : data).single_limit_minor)} · 每日 ${formatAmount((isObject(data.card) ? data.card : data).daily_limit_minor)}`,
      };
    }
    if (toolName === "card.apply") {
      const application = isObject(data.application) ? data.application : data;
      return {
        title: writeTitles[toolName],
        detail: `${stringValue(application.label)} · 等待处理，尚未发卡`,
      };
    }
    const card = isObject(data.card) ? data.card : data;
    const replacement = isObject(data.replacement_card)
      ? data.replacement_card
      : null;
    return {
      title: writeTitles[toolName] ?? "银行卡状态已更新",
      detail: replacement
        ? `旧卡尾号 ${stringValue(card.card_suffix)} 已停用 · 新卡尾号 ${stringValue(replacement.card_suffix)}`
        : `尾号 ${stringValue(card.card_suffix)}`,
    };
  }
  if (toolName.startsWith("subscription.")) {
    const subscription = isObject(data.subscription) ? data.subscription : data;
    return {
      title: writeTitles[toolName] ?? "自动扣费状态已更新",
      detail: stringValue(subscription.merchant),
    };
  }
  if (toolName.startsWith("transfer.")) {
    const transfer = isObject(data.transfer) ? data.transfer : data;
    return {
      title: writeTitles[toolName] ?? "转账状态已更新",
      detail: [
        stringValue(transfer.payee_name || data.title),
        typeof transfer.amount_minor === "number"
          ? formatAmount(transfer.amount_minor)
          : "",
      ]
        .filter(Boolean)
        .join(" · "),
    };
  }
  const order = isObject(data.order) ? data.order : data;
  return {
    title: writeTitles[toolName] ?? "理财状态已更新",
    detail: [
      stringValue(order.product_name),
      typeof order.amount_minor === "number"
        ? formatAmount(order.amount_minor)
        : "",
    ]
      .filter(Boolean)
      .join(" · "),
  };
}

export function TaskResult({
  task,
  compact = false,
  compactPrefix = "",
}: {
  task: Task;
  compact?: boolean;
  compactPrefix?: string;
}) {
  const results = task.steps
    .filter(
      (step) =>
        step.status === "succeeded" &&
        step.tool_name &&
        isObject(step.result_data),
    )
    .sort((a, b) => a.sequence - b.sequence);
  if (!results.length) return null;

  const writes = results.filter(
    (step) =>
      step.tool_name !== null && Object.hasOwn(writeTitles, step.tool_name),
  );
  const reads = results.filter(
    (step) =>
      step.tool_name !== null &&
      step.tool_name !== "investment.assessment_questions" &&
      !Object.hasOwn(writeTitles, step.tool_name) &&
      resultTitles[step.tool_name],
  );
  const hasAssessmentQuestions = results.some(
    (step) => step.tool_name === "investment.assessment_questions",
  );
  // Repeated reads can be collapsed. Every successful write remains a distinct result.
  const latestReads = new Map<string, Step>();
  for (const step of reads) latestReads.set(step.tool_name ?? "", step);
  const primaryReads = [...latestReads.values()]
    .sort(
      (a, b) =>
        readIntentScore(b.tool_name ?? "", task.request_text) -
          readIntentScore(a.tool_name ?? "", task.request_text) ||
        b.sequence - a.sequence,
    )
    .slice(0, 2);

  const resultContent = (
    <>
      {writes.length ? (
        <div className="result-group">
          <ul className="completed-change-list">
            {writes.map((step) => {
              const summary = writeSummary(step);
              return (
                <li key={step.id}>
                  <AppIcon
                    className="completed-change-mark"
                    name="check"
                    size={18}
                  />
                  <span>
                    <strong>{summary.title}</strong>
                    {summary.detail ? <small>{summary.detail}</small> : null}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {primaryReads.length ? (
        <div className="result-group">
          <h3>{writes.length ? "处理依据" : "查询结果"}</h3>
          <div className="result-summary-grid">
            {primaryReads.map((step) => (
              <article className="result-summary" key={step.id}>
                <h4>{resultTitles[step.tool_name ?? ""]}</h4>
                <ul>
                  {conciseValue(step).map((line, index) => (
                    <li key={`${step.id}-${index}`}>{line}</li>
                  ))}
                </ul>
                {step.tool_name?.startsWith("bill.anomalies") ? (
                  <p className="task-result-notice">
                    规则提示仅供核对，不代表欺诈结论。
                  </p>
                ) : null}
                {step.tool_name?.startsWith("investment.products") ||
                step.tool_name?.startsWith("investment.compare") ? (
                  <p className="task-result-notice">
                    产品与收益为虚拟信息，不构成投资建议。
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}
      {hasAssessmentQuestions ? <RiskAssessmentForm /> : null}
    </>
  );
  const fullResultContent = results.map((step) => {
    if (!step.tool_name || !isObject(step.result_data)) return null;
    if (step.tool_name === "investment.assessment_questions") {
      return compact ? <RiskAssessmentForm key={step.id} /> : null;
    }
    const detail = resultForTool(step.tool_name, step.result_data);
    return (
      <div className="full-result-item" key={step.id}>
        <h4>
          {resultTitles[step.tool_name] ??
            writeTitles[step.tool_name] ??
            "业务结果"}
        </h4>
        {detail ?? <p>{conciseValue(step).join("；") || "已执行"}</p>}
      </div>
    );
  });

  if (compact) {
    const compactSummary = writes.length
      ? writes.length > 1
        ? `已执行 ${writes.length} 项操作`
        : writes
            .map((step) => {
              const summary = writeSummary(step);
              return [summary.title, summary.detail]
                .filter(Boolean)
                .join(" · ");
            })
            .join("；")
      : task.request_text.length > 42
        ? `${task.request_text.slice(0, 42)}…`
        : task.request_text;

    return (
      <details className="historical-task-result">
        <summary>
          <span>
            {compactPrefix}
            {compactSummary || "查看本次结果"}
          </span>
          <span className="historical-result-action">查看结果</span>
        </summary>
        <section
          aria-label="业务结果"
          className="task-result-summary historical-result-content"
        >
          <div className="full-result-content">{fullResultContent}</div>
        </section>
      </details>
    );
  }

  return (
    <section aria-label="业务结果" className="task-result-summary">
      {resultContent}
      <details className="full-result-details">
        <summary>查看业务详情</summary>
        {fullResultContent}
      </details>
    </section>
  );
}
