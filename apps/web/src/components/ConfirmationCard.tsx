import { useState } from "react";

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

function personName(value: string): string {
  const labels: Record<string, string> = {
    "Demo User One": "本人",
    "Demo User Two": "模拟用户二",
  };
  return labels[value] ?? value;
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
    lost: "已挂失",
    replaced: "已补卡停用",
    pending_confirmation: "待提交",
    submitted: "待模拟审核",
    approved: "模拟审核通过",
    rejected: "模拟审核未通过",
    paused: "已暂停",
    cancelled: "已取消",
    awaiting_confirmation: "待确认",
    scheduled: "待执行",
    executed: "已执行",
    updated: "已更新",
    open: "待收款",
    settled: "已结清",
  };
  return labels[status] ?? "状态待更新";
}

function actionName(confirmation: Confirmation): string {
  const details = confirmation.details;
  if (confirmation.resource_type === "card")
    return confirmation.tool_name === "card.controls"
      ? "调整银行卡消费设置"
      : confirmation.tool_name === "card.purchase"
        ? "购买模拟商品"
        : confirmation.target_status === "frozen"
          ? "冻结银行卡"
          : confirmation.target_status === "lost"
            ? "挂失银行卡"
            : confirmation.target_status === "replaced"
              ? "模拟补卡"
              : "解冻银行卡";
  if (confirmation.resource_type === "card_application")
    return "提交模拟借记卡申请";
  if (confirmation.resource_type === "birthday_plan")
    return "保存生日预算与到期提醒";
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
  hasPreviousChanges,
  onConfirm,
  onCancel,
  onRefresh,
  refreshing,
}: {
  confirmation: Confirmation;
  busy: boolean;
  hasPreviousChanges: boolean;
  onConfirm: (code?: string) => void;
  onCancel: () => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const [verificationCode, setVerificationCode] = useState("");
  const needsVerification = confirmation.confirmation_method === "demo_otp";
  const details = confirmation.details;
  const action = actionName(confirmation);
  const resourceLabels: Record<Confirmation["resource_type"], string> = {
    card: "银行卡",
    card_application: "银行卡申请",
    birthday_plan: "生日计划",
    subscription: "自动扣费",
    transfer: "转账",
    split: "AA 分账",
    investment_order: "理财操作",
  };
  const impactLabels: Record<Confirmation["resource_type"], string> = {
    card:
      confirmation.tool_name === "card.purchase"
        ? "确认后将从这张卡绑定的模拟账户扣款，并生成模拟交易记录。"
        : confirmation.tool_name === "card.controls"
          ? "确认后会改变这张卡的模拟消费限制。"
          : confirmation.target_status === "replaced"
            ? "旧卡将永久停用，并创建一张新的模拟银行卡。新卡尾号由服务端生成。"
            : "只影响这张模拟银行卡。",
    card_application:
      "确认后仅提交模拟申请，等待本地模拟审核；不会立即发卡或产生真实授信。",
    birthday_plan:
      "仅保存预算意向和到期提醒，不冻结资金，也不会自动购买。到期后需要重新核对并确认每笔模拟消费。",
    subscription: "只改变这项模拟订阅的自动续费状态，不会向商户发起请求。",
    transfer: "这笔转账只在模拟账本中记账。",
    split: "仅更新这笔模拟 AA 分账的状态。",
    investment_order: "仅更新模拟资金和持仓，不代表真实收益。",
  };
  const detailsRows: Array<[string, string | null]> = [];

  if (
    confirmation.resource_type === "card" &&
    confirmation.tool_name === "card.controls"
  ) {
    detailsRows.push(
      ["单笔限额", amount(details, "single_limit_minor")],
      ["每日限额", amount(details, "daily_limit_minor")],
      [
        "线上消费",
        value(details, "online_enabled") === true ? "允许" : "已关闭",
      ],
    );
  } else if (
    confirmation.resource_type === "card" &&
    confirmation.tool_name === "card.purchase"
  ) {
    detailsRows.push(
      ["商品", text(details, "product_name")],
      [
        "数量",
        typeof value(details, "quantity") === "number"
          ? `${String(value(details, "quantity"))} 件`
          : null,
      ],
      ["金额", amount(details, "amount_minor")],
      [
        "消费方式",
        text(details, "channel") === "online" ? "模拟线上消费" : "模拟线下消费",
      ],
    );
  } else if (confirmation.resource_type === "card_application") {
    const account = text(details, "account_label");
    detailsRows.push([
      "绑定账户",
      account === "Everyday account"
        ? "日常账户"
        : account === "Savings account"
          ? "储蓄账户"
          : account,
    ]);
  } else if (confirmation.resource_type === "birthday_plan") {
    detailsRows.push(
      ["生日日期", text(details, "birthday_on")],
      ["提醒日期", text(details, "purchase_on")],
      ["计划预算", amount(details, "budget_minor")],
      ["鲜花和蛋糕参考总价", amount(details, "catalog_total_minor")],
      ["账户", text(details, "account_label")],
    );
  } else if (confirmation.resource_type === "transfer") {
    detailsRows.push(
      ["收款人", text(details, "payee_name")],
      ["付款账户", text(details, "source_account_label")],
      ["金额", amount(details, "amount_minor")],
      ["备注", text(details, "remark")],
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
                if (typeof item === "string") return personName(item);
                if (
                  typeof item === "object" &&
                  item !== null &&
                  "display_name" in item
                )
                  return personName(String(item.display_name));
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
          <span className="confirmation-kicker">待你确认</span>
          <h3 id="confirmation-title">{action}</h3>
        </div>
        <button
          className="confirmation-refresh"
          disabled={refreshing || busy}
          onClick={onRefresh}
          type="button"
        >
          {refreshing ? "更新中…" : "刷新状态"}
        </button>
      </div>

      <div className="confirmation-card-name">
        <AppIcon
          name={
            confirmation.resource_type === "card" ||
            confirmation.resource_type === "card_application"
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
              <div
                className={
                  label === "金额" || label === "总金额"
                    ? "confirmation-amount-row"
                    : undefined
                }
                key={label}
              >
                <dt>{label}</dt>
                <dd>{item}</dd>
              </div>
            ),
          )}
        </dl>
      ) : null}

      {confirmation.tool_name !== "card.controls" &&
      confirmation.tool_name !== "card.purchase" ? (
        <div aria-label="状态变化" className="state-change">
          <div>
            <span>当前状态</span>
            <strong>{statusName(confirmation.current_status)}</strong>
          </div>
          <AppIcon
            className="state-change-arrow"
            name="arrow-right"
            size={18}
          />
          <div>
            <span>操作后</span>
            <strong>{statusName(confirmation.target_status)}</strong>
          </div>
        </div>
      ) : null}

      <p className="confirmation-impact">
        {impactLabels[confirmation.resource_type]}
        {hasPreviousChanges ? "此前已完成的操作不会因取消任务而撤销。" : null}
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

      {needsVerification ? (
        <div className="confirmation-verification">
          <label htmlFor="demo-verification-code">模拟二次验证</label>
          <p>此操作风险较高。请从独立的本地演示验证通道获取六位验证码。</p>
          <input
            id="demo-verification-code"
            autoComplete="one-time-code"
            inputMode="numeric"
            maxLength={6}
            pattern="[0-9]{6}"
            type="text"
            value={verificationCode}
            onChange={(event) =>
              setVerificationCode(
                event.target.value.replace(/\D/g, "").slice(0, 6),
              )
            }
          />
        </div>
      ) : null}

      <div className="confirmation-actions">
        <button
          className="button button-primary"
          disabled={
            busy || (needsVerification && !/^[0-9]{6}$/.test(verificationCode))
          }
          onClick={() =>
            onConfirm(needsVerification ? verificationCode : undefined)
          }
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
          取消任务
        </button>
      </div>
    </section>
  );
}
