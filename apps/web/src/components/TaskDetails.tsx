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
  "subscription.confirmation_requested": "等待确认",
  "subscription.confirmation_invalidated": "确认已取消",
  "subscription.confirmation_rejected": "确认未通过",
  "subscription.confirmation_consumed": "操作已确认",
  "subscription.status_changed": "订阅状态变更",
  "transfer.confirmation_requested": "等待确认",
  "transfer.confirmation_invalidated": "确认已取消",
  "transfer.confirmation_rejected": "确认未通过",
  "transfer.confirmation_consumed": "转账已处理",
  "transfer.executed": "模拟转账完成",
  "split.confirmation_requested": "等待确认",
  "split.confirmation_consumed": "分账已处理",
  "investment_order.confirmation_requested": "等待确认",
  "investment_order.confirmation_consumed": "理财操作已处理",
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
    paused: "已暂停",
    cancelled: "已取消",
    planning: "正在处理",
    pending: "等待处理",
    succeeded: "已完成",
    failed: "失败",
    completed: "已完成",
    awaiting_confirmation: "等待确认",
    awaiting_input: "需要补充信息",
    running: "正在处理",
    scheduled: "待执行",
    executed: "已完成",
    open: "待收款",
    settled: "已结清",
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
    "bill.monthly_summary": "查询月度账单",
    "bill.transactions": "查询交易明细",
    "bill.anomalies": "检查异常消费",
    "subscription.list": "查询自动扣费",
    "subscription.pause": "暂停自动续费",
    "subscription.resume": "恢复自动续费",
    "subscription.cancel": "取消自动续费",
    "transfer.accounts": "查询账户余额",
    "transfer.payees": "查询收款人",
    "transfer.history": "查询转账记录",
    "transfer.create": "普通转账",
    "transfer.schedule": "定时转账",
    "transfer.cancel_scheduled": "取消定时转账",
    "transfer.simulate_due": "执行到期转账",
    "transfer.splits": "查询 AA 分账",
    "transfer.split_create": "创建 AA 分账",
    "transfer.split_collect": "模拟收款",
    "investment.products": "查询模拟理财产品",
    "investment.compare": "比较理财产品",
    "investment.profile": "查询风险等级",
    "investment.portfolio": "查询模拟持仓",
    "investment.orders": "查询理财记录",
    "investment.buy": "申购模拟理财",
    "investment.redeem": "赎回模拟理财",
    "finance.payday_plan": "计算发薪日资金安排",
  };
  return labels[key] ?? key;
}

function stepSummary(step: Task["steps"][number]): string {
  const key = step.tool_name ?? step.step_type;
  if (step.error_code === "superseded_by_new_input")
    return "补充信息更新后，原确认已取消。";
  if (key === "planner" && step.status === "failed")
    return "请求处理失败，请查看任务错误信息。";
  if (
    step.status === "awaiting_confirmation" &&
    (key.startsWith("card.") ||
      key.startsWith("subscription.") ||
      key.startsWith("transfer.") ||
      key.startsWith("investment."))
  )
    return "已生成待确认操作；业务状态尚未变更。";
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
    "bill.monthly_summary": "账单统计已读取。",
    "bill.transactions": "交易明细已读取。",
    "bill.anomalies": "异常消费检查已完成。",
    "subscription.list": "自动扣费信息已读取。",
    "subscription.pause": "自动续费已暂停。",
    "subscription.resume": "自动续费已恢复。",
    "subscription.cancel": "自动续费已取消。",
    "transfer.accounts": "账户余额已读取。",
    "transfer.payees": "收款人信息已读取。",
    "transfer.history": "转账记录已读取。",
    "transfer.splits": "AA 分账记录已读取。",
    "investment.products": "模拟理财产品已读取。",
    "investment.compare": "产品信息已按模拟数据比较。",
    "investment.profile": "模拟风险等级已读取。",
    "investment.portfolio": "模拟持仓已读取。",
    "investment.orders": "理财操作记录已读取。",
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
  refreshing,
  onRefresh,
  onCancel,
}: {
  task: Task | null;
  busy: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onCancel: () => void;
}) {
  const cancellable =
    task !== null &&
    ["pending", "planning", "awaiting_input", "awaiting_confirmation"].includes(
      task.status,
    );

  return (
    <section aria-labelledby="task-overview-title" className="context-section">
      <div className="section-heading task-heading">
        <div>
          <h2 id="task-overview-title">处理进度</h2>
          <p>{task ? "最近一项请求" : "尚无进行中的请求"}</p>
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
          <div className="task-overview-actions">
            <button
              className="text-button"
              disabled={refreshing}
              onClick={onRefresh}
              type="button"
            >
              {refreshing ? "正在读取…" : "刷新进度"}
            </button>
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
