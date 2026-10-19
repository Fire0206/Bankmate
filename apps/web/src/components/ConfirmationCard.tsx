import type { components } from "../generated/api";
import { AppIcon } from "./AppIcon";
import { cardLabel } from "./cardFormat";

type Confirmation = components["schemas"]["ConfirmationResponse"];
type Details = NonNullable<Confirmation["details"]>;

function value(details: Details | null | undefined, key: string): unknown {
  return details?.[key];
}

function text(details: Details | null | undefined, key: string): string | null {
  const item = value(details, key);
  return typeof item === "string" && item ? item : null;
}

function amount(
  details: Details | null | undefined,
  key: string,
): string | null {
  const item = value(details, key);
  if (typeof item !== "number" || !Number.isSafeInteger(item)) return null;
  const whole = Math.floor(item / 100).toLocaleString("zh-CN");
  const fraction = String(item % 100).padStart(2, "0");
  return `¥${whole}.${fraction}`;
}

function statusName(status: string): string {
  const labels: Record<string, string> = {
    active: "正常",
    frozen: "已冻结",
    paused: "已暂停",
    cancelled: "已取消",
    awaiting_confirmation: "待确认",
    scheduled: "待执行",
    executed: "已执行",
    open: "待收款",
    settled: "已结清",
  };
  return labels[status] ?? status;
}

function actionName(confirmation: Confirmation): string {
  const details = confirmation.details;
  if (confirmation.resource_type === "card")
    return confirmation.target_status === "frozen"
      ? "冻结银行卡"
      : "解冻银行卡";
  if (confirmation.resource_type === "subscription") {
    return confirmation.target_status === "paused"
      ? "暂停自动续费"
      : confirmation.target_status === "cancelled"
        ? "取消自动续费"
        : "恢复自动续费";
  }
  if (confirmation.resource_type === "transfer") {
    return confirmation.target_status === "cancelled"
      ? "取消定时转账"
      : text(details, "transfer_type") === "scheduled"
        ? "创建定时转账"
        : "转账";
  }
  if (confirmation.resource_type === "split")
    return confirmation.target_status === "settled"
      ? "模拟收取分账"
      : "创建 AA 分账";
  return text(details, "order_type") === "redeem" ? "赎回理财" : "申购理财";
}

function expiryLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "有效期信息暂不可用";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function ConfirmationCard({
  confirmation,
  busy,
  onConfirm,
  onCancel,
}: {
  confirmation: Confirmation;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const details = confirmation.details;
  const action = actionName(confirmation);
  const resourceLabels: Record<Confirmation["resource_type"], string> = {
    card: "银行卡",
    subscription: "自动扣费",
    transfer: "转账",
    split: "AA 分账",
    investment_order: "理财操作",
  };
  const detailsRows: Array<[string, string | null]> = [];

  if (confirmation.resource_type === "transfer") {
    detailsRows.push(
      ["收款人", text(details, "payee_name")],
      ["付款账户", text(details, "source_account_label")],
      ["金额", amount(details, "amount_minor")],
      [
        "执行时间",
        text(details, "scheduled_at")
          ? expiryLabel(text(details, "scheduled_at")!)
          : "确认后模拟执行",
      ],
    );
  } else if (confirmation.resource_type === "split") {
    detailsRows.push(
      ["总金额", amount(details, "total_amount_minor")],
      [
        "参与人",
        Array.isArray(value(details, "participants"))
          ? (value(details, "participants") as unknown[])
              .map((item) => {
                if (typeof item === "string") return item;
                if (
                  typeof item === "object" &&
                  item !== null &&
                  "display_name" in item
                )
                  return String(item.display_name);
                return "";
              })
              .filter(Boolean)
              .join("、")
          : null,
      ],
    );
  } else if (confirmation.resource_type === "investment_order") {
    detailsRows.push(
      ["金额", amount(details, "amount_minor")],
      ["付款账户", text(details, "account_label")],
      [
        "风险等级",
        typeof value(details, "risk_level") === "number"
          ? `R${String(value(details, "risk_level"))}`
          : null,
      ],
    );
  }

  return (
    <section aria-labelledby="confirmation-title" className="confirmation-card">
      <div className="confirmation-heading">
        <div>
          <p className="section-kicker">请核对操作</p>
          <h3 id="confirmation-title">确认{action}</h3>
        </div>
        <span className="confirmation-mark">
          <AppIcon name="info" size={17} />
          需要确认
        </span>
      </div>

      <div className="confirmation-card-name">
        <AppIcon
          name={
            confirmation.resource_type === "card"
              ? "cards"
              : confirmation.resource_type === "investment_order"
                ? "wealth"
                : confirmation.resource_type === "transfer"
                  ? "transfer"
                  : "subscriptions"
          }
          size={19}
        />
        <span>
          <strong>
            {confirmation.resource_type === "card"
              ? cardLabel(confirmation.resource_label)
              : confirmation.resource_label}
          </strong>
          <small>
            {confirmation.resource_type === "card"
              ? `尾号 ${confirmation.card_suffix ?? "—"}`
              : resourceLabels[confirmation.resource_type]}
          </small>
        </span>
      </div>

      {detailsRows.some(([, item]) => item !== null) ? (
        <dl className="confirmation-details">
          {detailsRows.map(([label, item]) =>
            item === null ? null : (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{item}</dd>
              </div>
            ),
          )}
        </dl>
      ) : null}

      <div aria-label="状态变化" className="state-change">
        <div>
          <span>当前状态</span>
          <strong>{statusName(confirmation.current_status)}</strong>
        </div>
        <AppIcon className="state-change-arrow" name="arrow-right" size={18} />
        <div>
          <span>操作后</span>
          <strong>{statusName(confirmation.target_status)}</strong>
        </div>
      </div>

      <p className="confirmation-impact">
        仅影响当前模拟{resourceLabels[confirmation.resource_type]}
        ，不会连接真实银行或支付网络。
      </p>
      <p className="confirmation-expiry">
        <AppIcon name="clock" size={15} />
        <span>
          请在{" "}
          <time dateTime={confirmation.expires_at}>
            {expiryLabel(confirmation.expires_at)}
          </time>{" "}
          前确认
        </span>
      </p>

      <div className="confirmation-actions">
        <button
          className="button button-primary"
          disabled={busy}
          onClick={onConfirm}
          type="button"
        >
          {busy ? "正在处理…" : `确认${action}`}
        </button>
        <button
          className="button button-secondary"
          disabled={busy}
          onClick={onCancel}
          type="button"
        >
          取消操作
        </button>
      </div>
    </section>
  );
}
