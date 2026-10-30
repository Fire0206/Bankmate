import type { AgentTaskHistoryResponse } from "../api/client";
import { AppIcon } from "./AppIcon";
import { statusLabel } from "./taskFormat";

type TaskHistoryItem = AgentTaskHistoryResponse["items"][number];

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function TaskHistory({
  items,
  loading,
  error,
  selectedId,
  disabled,
  onSelect,
  onRefresh,
}: {
  items: TaskHistoryItem[];
  loading: boolean;
  error: string | null;
  selectedId?: string;
  disabled: boolean;
  onSelect: (taskId: string) => void;
  onRefresh: () => void;
}) {
  return (
    <section
      aria-labelledby="task-history-title"
      className="task-history-panel"
    >
      <header>
        <div>
          <h2 id="task-history-title">最近办理</h2>
          <span>可重新查看任务进度与结果</span>
        </div>
        <button
          aria-label="刷新办理记录"
          className="task-history-refresh"
          disabled={loading}
          onClick={onRefresh}
          type="button"
        >
          <AppIcon name="refresh" size={16} />
          刷新
        </button>
      </header>
      {error ? (
        <p className="task-history-error" role="alert">
          {error}
        </p>
      ) : loading ? (
        <p className="task-history-empty" role="status">
          正在读取办理记录…
        </p>
      ) : items.length === 0 ? (
        <p className="task-history-empty">暂无办理记录。</p>
      ) : (
        <ul className="task-history-list">
          {items.slice(0, 6).map((item) => (
            <li key={item.id}>
              <button
                aria-current={selectedId === item.id ? "true" : undefined}
                className="task-history-row"
                disabled={disabled}
                onClick={() => onSelect(item.id)}
                type="button"
              >
                <span className="task-history-copy">
                  <strong>{item.request_text.split("\n")[0]}</strong>
                  <small>
                    {dateLabel(item.updated_at)}
                    {item.message ? ` · ${item.message}` : ""}
                  </small>
                </span>
                <span className={"task-status task-status-" + item.status}>
                  {statusLabel(item.status)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
