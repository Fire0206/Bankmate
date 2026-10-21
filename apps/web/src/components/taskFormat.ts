import type { components } from "../generated/api";
import type { IconName } from "./AppIcon";

type Task = components["schemas"]["AgentTaskResponse"];

export const statusLabels: Record<Task["status"], string> = {
  pending: "等待处理",
  planning: "正在处理",
  awaiting_input: "需要补充信息",
  awaiting_confirmation: "等待确认",
  running: "正在处理",
  completed: "已完成",
  failed: "操作失败",
  cancelled: "已取消",
};

export function statusLabel(status: Task["status"]): string {
  return statusLabels[status];
}

export function taskStatusIcon(status: Task["status"]): IconName {
  if (status === "completed") return "check";
  if (status === "failed" || status === "awaiting_confirmation") return "alert";
  if (status === "cancelled") return "close";
  if (status === "awaiting_input") return "info";
  return "clock";
}

const changeTools = new Set([
  "card.freeze",
  "card.unfreeze",
  "subscription.pause",
  "subscription.resume",
  "subscription.cancel",
  "transfer.create",
  "transfer.schedule",
  "transfer.cancel_scheduled",
  "transfer.split_create",
  "transfer.split_collect",
  "investment.buy",
  "investment.redeem",
]);

export function hasSuccessfulChange(task: Task): boolean {
  return task.steps.some(
    (step) =>
      step.status === "succeeded" &&
      step.tool_name !== null &&
      changeTools.has(step.tool_name),
  );
}

export function taskStatusLabel(task: Task): string {
  if (task.status === "failed" && hasSuccessfulChange(task)) return "部分完成";
  return statusLabel(task.status);
}

export function taskMessage(task: Task): string {
  if (task.status === "awaiting_confirmation")
    return "请核对下面的操作内容。确认前，业务状态不会变更。";
  if (task.status === "awaiting_input")
    return task.message || "请补充必要信息后继续。";
  if (task.status !== "failed") return task.message;
  const known: Record<string, string> = {
    provider_not_configured: "当前无法处理这项请求，请稍后再试。",
    card_not_found: "没有找到这张银行卡，请检查尾号后重试。",
    subscription_not_found: "没有找到这项自动扣费，请检查订阅名称。",
    invalid_subscription_transition: "这项订阅当前无法变更到请求的状态。",
    unknown_tool: "这项业务操作暂不支持，状态没有改变。",
    tool_input_invalid: "请求信息无法识别，请重新描述。",
    agent_step_limit_exceeded: "任务未能完成，请重新描述操作。",
    confirmation_expired: "确认已过期，业务状态没有变更。请重新发起请求。",
  };
  if (task.error_code && known[task.error_code]) return known[task.error_code];
  return hasSuccessfulChange(task)
    ? "后续步骤未完成，已完成的操作仍然有效。请查看实际状态后再继续。"
    : "这项请求未能完成，业务状态没有确认变更。请调整请求后重试。";
}
