import type { components } from "../generated/api";
import { AppIcon } from "./AppIcon";
import { cardLabel } from "./cardFormat";

type Confirmation = components["schemas"]["ConfirmationResponse"];

function statusName(status: Confirmation["current_status"]): string {
  return status === "active" ? "正常" : "已冻结";
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
  const action = confirmation.target_status === "frozen" ? "冻结" : "解冻";

  return (
    <section aria-labelledby="confirmation-title" className="confirmation-card">
      <div className="confirmation-heading">
        <div>
          <p className="section-kicker">请核对操作</p>
          <h3 id="confirmation-title">确认{action}银行卡</h3>
        </div>
        <span className="confirmation-mark">
          <AppIcon name="info" size={17} />
          需要确认
        </span>
      </div>

      <div className="confirmation-card-name">
        <AppIcon name="cards" size={19} />
        <span>
          <strong>{cardLabel(confirmation.card_label)}</strong>
          <small>尾号 {confirmation.card_suffix}</small>
        </span>
      </div>

      <div aria-label="银行卡状态变化" className="state-change">
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

      <p className="confirmation-impact">影响范围：仅限这张演示银行卡。</p>
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
