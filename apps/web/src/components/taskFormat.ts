import type { components } from "../generated/api";

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

export function taskMessage(task: Task): string {
  if (task.status !== "failed") return task.message;
  const known: Record<string, string> = {
    provider_not_configured: "模型服务尚未配置，任务没有执行。",
    card_not_found: "没有找到这张银行卡，请检查尾号后重试。",
    subscription_not_found: "没有找到这项自动扣费，请检查订阅名称。",
    invalid_subscription_transition: "这项订阅当前无法变更到请求的状态。",
    unknown_tool: "这项业务操作暂不支持，状态没有改变。",
    tool_input_invalid: "请求信息无法识别，请重新描述。",
    agent_step_limit_exceeded: "任务未能完成，请重新描述操作。",
  };
  return known[task.error_code ?? ""] ?? task.message;
}
