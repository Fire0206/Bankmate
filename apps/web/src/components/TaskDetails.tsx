import type { components } from "../generated/api";
import type { ApiError } from "../api/client";
import { AppIcon } from "./AppIcon";
import { hasSuccessfulChange, taskStatusLabel } from "./taskFormat";

type Task = components["schemas"]["AgentTaskResponse"];
type AuditEvent = components["schemas"]["AgentAuditEventResponse"];

const actionLabels: Record<string, string> = {
  "card.freeze": "冻结银行卡",
  "card.unfreeze": "解冻银行卡",
  "subscription.pause": "暂停自动续费",
  "subscription.resume": "恢复自动续费",
  "subscription.cancel": "取消自动续费",
  "transfer.create": "转账",
  "transfer.schedule": "创建定时转账",
  "transfer.cancel_scheduled": "取消定时转账",
  "transfer.split_create": "创建 AA 分账",
  "transfer.split_collect": "模拟收取分账",
  "investment.buy": "申购模拟理财",
  "investment.redeem": "赎回模拟理财",
};

const businessEventLabels: Record<string, string> = {
  "card.status_changed": "银行卡状态变更",
  "subscription.status_changed": "自动扣费状态变更",
  "transfer.executed": "模拟转账完成",
  "transfer.scheduled": "定时转账已创建",
  "transfer.cancelled": "定时转账已取消",
  "split.status_changed": "AA 分账状态变更",
  "investment.buy_executed": "模拟申购完成",
  "investment.redeem_executed": "模拟赎回完成",
};

const stateLabels: Record<string, string> = {
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

function dateTimeLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间暂不可用";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function knownState(value: unknown): string | null {
  if (typeof value !== "string") return null;
  return stateLabels[value] ?? null;
}

function eventSummary(event: AuditEvent): string {
  const before = knownState(event.before_state?.status);
  const after = knownState(event.after_state?.status);
  if (before && after) return `${before} → ${after}`;
  return event.outcome === "succeeded"
    ? "已完成"
    : event.outcome === "failed"
      ? "未完成"
      : "已记录";
}

function stepLabel(step: Task["steps"][number]): string | null {
  if (step.tool_name && actionLabels[step.tool_name])
    return actionLabels[step.tool_name];
  if (step.step_type === "cancellation") return "取消任务";
  if (step.step_type === "user_input") return "补充信息";
  if (step.status === "failed") return "未完成的步骤";
  return null;
}

function stepStatus(step: Task["steps"][number]): string {
  if (step.status === "awaiting_confirmation") return "待确认";
  if (step.status === "succeeded") return "已执行";
  if (step.status === "cancelled") return "已取消";
  if (step.status === "failed") return "未完成";
  return "处理中";
}

function shouldShowStep(step: Task["steps"][number]): boolean {
  return Boolean(stepLabel(step));
}

export function TaskDetails({
  task,
  busy,
  refreshing,
  onRefresh,
  onCancel,
  open,
  onOpenChange,
  audit,
  auditLoading,
  auditError,
}: {
  task: Task;
  busy: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onCancel: () => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  audit: AuditEvent[];
  auditLoading: boolean;
  auditError: ApiError | Error | null;
}) {
  const cancellable = [
    "pending",
    "planning",
    "awaiting_input",
    "awaiting_confirmation",
  ].includes(task.status);
  const visibleSteps = task.steps.filter(shouldShowStep);
  const businessEvents = audit.filter((event) =>
    Object.hasOwn(businessEventLabels, event.event_type),
  );

  return (
    <section className="task-activity" aria-label="处理进度与记录">
      <div className="task-activity-head">
        <span
          className={
            "task-status task-status-" +
            (task.status === "failed" && hasSuccessfulChange(task)
              ? "partial"
              : task.status)
          }
          role="status"
        >
          {taskStatusLabel(task)}
        </span>
        <div className="task-activity-actions">
          <button
            className="text-button"
            disabled={refreshing}
            onClick={onRefresh}
            type="button"
          >
            {refreshing ? "正在刷新…" : "刷新状态"}
          </button>
          {cancellable && !task.confirmation ? (
            <button
              className="text-button cancel-task-button"
              disabled={busy}
              onClick={onCancel}
              type="button"
            >
              取消任务
            </button>
          ) : null}
        </div>
      </div>

      {task.status === "failed" && hasSuccessfulChange(task) ? (
        <p className="partial-completion-note">
          后续步骤未完成；已经执行的操作仍然有效。
        </p>
      ) : cancellable && !task.confirmation && hasSuccessfulChange(task) ? (
        <p className="partial-completion-note">
          取消任务不会撤销已经执行的操作。
        </p>
      ) : null}

      <details
        className="task-details"
        id="task-details"
        onToggle={(event) => onOpenChange(event.currentTarget.open)}
        open={open}
      >
        <summary>
          <span>查看处理记录</span>
          <AppIcon className="details-chevron" name="chevron-down" size={17} />
        </summary>
        <div className="details-content">
          {visibleSteps.length ? (
            <>
              <h3 className="details-subheading">处理步骤</h3>
              <ol className="step-list">
                {visibleSteps.map((step) => (
                  <li className="step-row" key={step.id}>
                    <span
                      aria-hidden="true"
                      className={
                        "step-marker step-marker-" +
                        step.status.replaceAll("_", "-")
                      }
                    />
                    <span className="step-copy">
                      <strong>{stepLabel(step)}</strong>
                      {step.status === "awaiting_confirmation" ? (
                        <span>确认前不会变更业务状态。</span>
                      ) : step.status === "failed" ? (
                        <span>请刷新后核对当前状态，再决定下一步。</span>
                      ) : null}
                    </span>
                    <span className="step-state">{stepStatus(step)}</span>
                  </li>
                ))}
              </ol>
            </>
          ) : null}

          <h3 className="details-subheading audit-subheading">状态变更</h3>
          {auditLoading ? (
            <p className="inline-empty" role="status">
              正在读取操作记录…
            </p>
          ) : auditError ? (
            <p className="inline-empty" role="alert">
              暂时无法读取操作记录，请稍后刷新。
            </p>
          ) : businessEvents.length === 0 ? (
            <p className="inline-empty">这项请求没有产生业务状态变更。</p>
          ) : (
            <ol className="audit-list">
              {businessEvents.map((event) => (
                <li className="audit-row" key={event.id}>
                  <span className="audit-label">
                    {businessEventLabels[event.event_type]}
                  </span>
                  <span className="audit-summary">{eventSummary(event)}</span>
                  <time dateTime={event.occurred_at}>
                    {dateTimeLabel(event.occurred_at)}
                  </time>
                </li>
              ))}
            </ol>
          )}

          {import.meta.env.DEV ? (
            <details className="developer-diagnostics">
              <summary>本地开发诊断</summary>
              <dl className="task-metadata">
                <div>
                  <dt>任务编号</dt>
                  <dd>
                    <code>{task.id}</code>
                  </dd>
                </div>
                {task.error_code ? (
                  <div>
                    <dt>错误代码</dt>
                    <dd>
                      <code>{task.error_code}</code>
                    </dd>
                  </div>
                ) : null}
                {task.steps.map((step) => (
                  <div key={step.id}>
                    <dt>步骤 {step.sequence}</dt>
                    <dd>
                      <code>
                        {step.tool_name ?? step.step_type} · {step.status}
                        {step.error_code ? ` · ${step.error_code}` : ""}
                      </code>
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          ) : null}
        </div>
      </details>
    </section>
  );
}
