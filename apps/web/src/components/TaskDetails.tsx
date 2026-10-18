import type { components } from "../generated/api";
import { AppIcon } from "./AppIcon";
import type { ApiError } from "../api/client";

type Task = components["schemas"]["AgentTaskResponse"];
type AuditEvent = components["schemas"]["AgentAuditEventResponse"];
import { statusLabels } from "./taskFormat";

const eventLabels: Record<string, string> = {
  "agent.task_created": "提交请求",
  "agent.task_input_received": "补充信息",
  "agent.tool_execution_succeeded": "查询完成",
  "agent.tool_execution_failed": "处理失败",
  "agent.task_state_changed": "处理状态更新",
  "agent.task_cancelled": "取消任务",
  "card.confirmation_requested": "等待确认",
  "card.confirmation_invalidated": "确认已取消",
  "card.confirmation_rejected": "确认未通过",
  "card.confirmation_consumed": "操作已确认",
  "card.status_changed": "银行卡状态变更",
};

function dateTimeLabel(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function plainStatus(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const labels: Record<string, string> = {
    active: "正常",
    frozen: "已冻结",
    planning: "正在处理",
    pending: "等待处理",
    succeeded: "已完成",
    failed: "失败",
    cancelled: "已取消",
    completed: "已完成",
    awaiting_confirmation: "等待确认",
    awaiting_input: "需要补充信息",
    running: "正在处理",
  };
  return labels[value] ?? value;
}

function stepLabel(step: Task["steps"][number]): string {
  const key = step.tool_name ?? step.step_type;
  const labels: Record<string, string> = {
    planner: "请求分析",
    user_input: "补充信息",
    cancellation: "取消任务",
    "card.list": "查询银行卡",
    "card.get": "查询卡片状态",
    "card.freeze": "冻结银行卡",
    "card.unfreeze": "解冻银行卡",
  };
  return labels[key] ?? key;
}

function stepSummary(step: Task["steps"][number]): string {
  const key = step.tool_name ?? step.step_type;
  if (step.error_code === "superseded_by_new_input")
    return "补充信息更新后，原确认已取消。";
  if (key === "planner" && step.status === "failed")
    return "请求处理失败，请查看任务错误信息。";
  if (step.status === "awaiting_confirmation" && key.startsWith("card."))
    return "已生成待确认操作；银行卡尚未变更。";
  if (step.status === "cancelled" && key === "cancellation")
    return "任务已取消，待执行操作没有发生。";
  if (step.status !== "succeeded") return step.summary;

  const summaries: Record<string, string> = {
    planner: "请求分析完成。",
    user_input: "已收到补充信息。",
    cancellation: "任务已取消，待执行操作没有发生。",
    "card.list": "银行卡信息已读取，卡片状态未变更。",
    "card.get": "卡片状态已查询。",
    "card.freeze": "银行卡已冻结。",
    "card.unfreeze": "银行卡已解冻。",
  };
  return summaries[key] ?? step.summary;
}

function eventSummary(event: AuditEvent): string {
  const before = plainStatus(event.before_state?.status);
  const after = plainStatus(event.after_state?.status);
  if (before && after) return before + " → " + after;
  return event.outcome === "succeeded"
    ? "已完成"
    : event.outcome === "failed"
      ? "未完成"
      : "已记录";
}

export function TaskOverview({
  task,
  busy,
  onCancel,
}: {
  task: Task | null;
  busy: boolean;
  onCancel: () => void;
}) {
  const cancellable =
    task !== null &&
    ["pending", "planning", "awaiting_input"].includes(task.status);

  return (
    <section aria-labelledby="task-overview-title" className="context-section">
      <div className="section-heading task-heading">
        <div>
          <h2 id="task-overview-title">处理进度</h2>
          <p>{task ? "最近一项银行卡请求" : "尚无进行中的请求"}</p>
        </div>
        {task ? (
          <span className={"task-status task-status-" + task.status}>
            {statusLabels[task.status]}
          </span>
        ) : null}
      </div>
      {task ? (
        <div className="task-overview-content">
          <div className="task-updated">
            <AppIcon name="clock" size={15} />
            <time dateTime={task.updated_at}>
              更新于 {dateTimeLabel(task.updated_at)}
            </time>
          </div>
          {cancellable ? (
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
      ) : (
        <p className="inline-empty">发送请求后，这里会显示真实处理状态。</p>
      )}
    </section>
  );
}

export function TaskDetails({
  task,
  open,
  onOpenChange,
  audit,
  auditLoading,
  auditError,
}: {
  task: Task | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  audit: AuditEvent[];
  auditLoading: boolean;
  auditError: ApiError | Error | null;
}) {
  return (
    <details
      className="task-details"
      id="task-details"
      onToggle={(event) => onOpenChange(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span>查看处理详情</span>
        <AppIcon className="details-chevron" name="chevron-down" size={17} />
      </summary>
      {!task ? (
        <p className="inline-empty">还没有可查看的任务。</p>
      ) : (
        <div className="details-content">
          <dl className="task-metadata">
            <div>
              <dt>任务编号</dt>
              <dd>
                <code>{task.id}</code>
              </dd>
            </div>
            <div>
              <dt>运行模式</dt>
              <dd>
                {task.provider_mode === "fake"
                  ? "确定性模拟规则"
                  : "兼容模型服务"}
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
          </dl>
          {task.status === "failed" ? (
            <div className="raw-task-error">
              <strong>服务端返回</strong>
              <p>{task.message}</p>
            </div>
          ) : null}

          <h3 className="details-subheading">处理步骤</h3>
          {task.steps.length === 0 ? (
            <p className="inline-empty">暂无处理步骤。</p>
          ) : (
            <ol className="step-list">
              {task.steps.map((step) => (
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
                    <span>{stepSummary(step)}</span>
                    {step.error_code ? <code>{step.error_code}</code> : null}
                  </span>
                  <span className="step-state">
                    {plainStatus(step.status) ?? step.status}
                  </span>
                </li>
              ))}
            </ol>
          )}

          <h3 className="details-subheading audit-subheading">操作记录</h3>
          {auditLoading ? (
            <p className="inline-empty" role="status">
              正在读取操作记录…
            </p>
          ) : auditError ? (
            <div className="audit-load-error" role="alert">
              无法读取操作记录：{auditError.message}
            </div>
          ) : audit.length === 0 ? (
            <p className="inline-empty">暂无操作记录。</p>
          ) : (
            <ol className="audit-list">
              {audit.map((event) => (
                <li className="audit-row" key={event.id}>
                  <span className="audit-label">
                    {eventLabels[event.event_type] ?? event.event_type}
                  </span>
                  <span className="audit-summary">{eventSummary(event)}</span>
                  <time dateTime={event.occurred_at}>
                    {dateTimeLabel(event.occurred_at)}
                  </time>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </details>
  );
}
