import { useEffect, useState } from "react";

import type { AgentTaskResponse } from "../api/client";
import { apiClient } from "../api/client";
import type { components } from "../generated/api";

type Handoff = components["schemas"]["HandoffResponse"];

export function TaskHandoffAction({ task }: { task: AgentTaskResponse }) {
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  const [loadedTaskId, setLoadedTaskId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{
    taskId: string;
    message: string;
  } | null>(null);
  const visible = task.status === "failed" || task.status === "awaiting_input";
  const taskError = error?.taskId === task.id ? error.message : null;

  useEffect(() => {
    let current = true;
    if (!visible) return;
    apiClient.readHandoff(task.id).then(
      (value) => {
        if (!current) return;
        setHandoff(value);
        setError(null);
        setLoadedTaskId(task.id);
      },
      () => {
        if (!current) return;
        setError({
          taskId: task.id,
          message: "无法读取协助请求状态，请稍后刷新任务。",
        });
        setLoadedTaskId(task.id);
      },
    );
    return () => {
      current = false;
    };
  }, [task.id, task.updated_at, visible]);

  async function requestAssistance() {
    setBusy(true);
    setError(null);
    try {
      setHandoff(await apiClient.requestHandoff(task.id, "user_requested"));
    } catch (caught) {
      setError({
        taskId: task.id,
        message:
          caught instanceof Error ? caught.message : "暂时无法提交协助请求。",
      });
    } finally {
      setBusy(false);
    }
  }

  if (!visible) return null;

  return (
    <section aria-label="人工协助" className="task-handoff-action">
      {handoff?.task_id === task.id ? (
        <div className="task-handoff-state" role="status">
          <strong>
            协助请求
            {handoff.status === "pending"
              ? "已记录，等待处理"
              : handoff.status === "in_progress"
                ? "正在处理"
                : "已处理"}
          </strong>
          {handoff.outcome ? <span>{handoff.outcome}</span> : null}
        </div>
      ) : (
        <button
          disabled={busy || loadedTaskId !== task.id || Boolean(taskError)}
          onClick={() => void requestAssistance()}
          type="button"
        >
          {busy ? "正在提交…" : "申请人工协助"}
        </button>
      )}
      {taskError ? <p role="alert">{taskError}</p> : null}
      <small>
        请求会保存在办理记录中；当前页面尚未连接人工客服，也不会执行金融操作。
      </small>
    </section>
  );
}
