import type { components } from "../generated/api";
import { AppIcon } from "./AppIcon";
import { cardLabel } from "./cardFormat";

type Confirmation = components["schemas"]["ConfirmationResponse"];

function statusName(status: Confirmation["current_status"]): string {
  const labels: Record<Confirmation["current_status"], string> = {
    active: "正常",
    frozen: "已冻结",
    paused: "已暂停",
    cancelled: "已取消",
  };
  return labels[status];
}

function expiryLabel(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
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
  const action = {
    frozen: "冻结",
    active: confirmation.resource_type === "card" ? "解冻" : "恢复",
    paused: "暂停",
    cancelled: "取消",
  }[confirmation.target_status];
  const resource =
    confirmation.resource_type === "card" ? "银行卡" : "自动续费";

  return (
    <section aria-labelledby="confirmation-title" className="confirmation-card">
      <div className="confirmation-heading">
        <div>
          <p className="section-kicker">请核对操作</p>
          <h3 id="confirmation-title">
            确认{action}
            {resource}
          </h3>
        </div>
        <span className="confirmation-mark">
          <AppIcon name="info" size={17} />
          需要确认
        </span>
      </div>

      <div className="confirmation-card-name">
        <AppIcon name="cards" size={19} />
        <span>
          <strong>
            {confirmation.resource_type === "card"
              ? cardLabel(confirmation.resource_label)
              : confirmation.resource_label}
          </strong>
          <small>
            {confirmation.resource_type === "card"
              ? `尾号 ${confirmation.card_suffix ?? "—"}`
              : "月度自动扣费"}
          </small>
        </span>
      </div>

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
        影响范围：仅限这项模拟
        {confirmation.resource_type === "card" ? "银行卡" : "订阅"}。
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
          {busy ? "正在处理…" : "确认" + action}
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
