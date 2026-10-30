import { useCallback, useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type {
  SubscriptionListResponse,
  SubscriptionReminderListResponse,
  SubscriptionResponse,
} from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { SkeletonLine, SkeletonRows } from "../components/Skeleton";

function money(value: number, currency = "CNY"): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value / 100);
}

function nextCharge(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
  }).format(new Date(value));
}

export function SubscriptionsPage({
  refreshKey,
  busy,
  onPrompt,
}: {
  refreshKey: string;
  busy: boolean;
  onPrompt: (prompt: string) => void;
}) {
  const [data, setData] = useState<SubscriptionListResponse | null>(null);
  const [reminders, setReminders] =
    useState<SubscriptionReminderListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [reminderBusy, setReminderBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [subscriptions, upcoming] = await Promise.all([
        apiClient.readSubscriptions(),
        apiClient.readSubscriptionReminders(),
      ]);
      setData(subscriptions);
      setReminders(upcoming);
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "暂时无法读取订阅信息。",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshKey]);

  const activeCount =
    data?.items.filter((item) => item.status === "active").length ?? 0;

  async function refreshReminders() {
    setReminderBusy(true);
    setError(null);
    try {
      setReminders(await apiClient.refreshSubscriptionReminders());
      setData(await apiClient.readSubscriptions());
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "暂时无法检查续费提醒。",
      );
    } finally {
      setReminderBusy(false);
    }
  }

  async function updateReminder(
    subscription: SubscriptionResponse,
    daysBefore: number,
  ) {
    setReminderBusy(true);
    setError(null);
    try {
      const updated = await apiClient.setSubscriptionReminder(subscription.id, {
        days_before: daysBefore,
        expected_version: subscription.version,
      });
      setData((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.id === updated.id ? updated : item,
              ),
            }
          : current,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提醒设置没有保存。");
    } finally {
      setReminderBusy(false);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        actionLabel="检查不必要订阅"
        busy={busy}
        onAction={() => onPrompt("看看我有哪些自动扣费，哪些可能不再需要")}
        title="订阅与代扣"
      />

      <div className="reminder-banner">
        <span>
          <strong>{reminders?.items.length ?? 0} 项</strong> 即将续费
        </span>
        <button
          disabled={reminderBusy}
          onClick={() => void refreshReminders()}
          type="button"
        >
          {reminderBusy ? "检查中…" : "检查到期提醒"}
        </button>
      </div>

      <div className="subscription-summary">
        <div>
          <span>每月固定扣费</span>
          <strong>
            {loading ? (
              <SkeletonLine width="96px" />
            ) : (
              money(data?.monthly_total_minor ?? 0, data?.currency)
            )}
          </strong>
        </div>
        <div>
          <span>生效中的订阅</span>
          <strong>
            {loading ? <SkeletonLine width="42px" /> : activeCount}
          </strong>
        </div>
        <div>
          <span>即将扣款</span>
          <strong>
            {loading ? (
              <SkeletonLine width="76px" />
            ) : data?.items.length ? (
              nextCharge(
                [...data.items]
                  .filter((item) => item.status === "active")
                  .sort(
                    (a, b) =>
                      new Date(a.next_charge_at).getTime() -
                      new Date(b.next_charge_at).getTime(),
                  )[0]?.next_charge_at ?? data.items[0].next_charge_at,
              )
            ) : (
              "—"
            )}
          </strong>
        </div>
      </div>

      {error ? (
        <div className="page-error" role="alert">
          {error}
          <button
            onClick={() => {
              setLoading(true);
              void load();
            }}
            type="button"
          >
            重新读取
          </button>
        </div>
      ) : null}

      <section className="subscriptions-card">
        <header>
          <h2>周期扣费清单</h2>
        </header>
        {loading ? (
          <SkeletonRows count={5} />
        ) : data?.items.length ? (
          <div className="subscription-list">
            {data.items.map((subscription) => (
              <article className="subscription-row" key={subscription.id}>
                <span className="subscription-logo">
                  {subscription.merchant.slice(0, 1)}
                </span>
                <span className="subscription-main">
                  <strong>{subscription.merchant}</strong>
                  <small>
                    每月{" "}
                    {money(subscription.amount_minor, subscription.currency)}
                    {" · "}
                    {subscription.status === "active"
                      ? `下次 ${nextCharge(subscription.next_charge_at)}`
                      : subscription.status === "paused"
                        ? "已暂停续费"
                        : "已取消"}
                  </small>
                </span>
                <div className="subscription-actions">
                  {subscription.status === "active" ? (
                    <button
                      disabled={busy}
                      onClick={() =>
                        onPrompt(`暂停${subscription.merchant}自动续费`)
                      }
                      type="button"
                    >
                      暂停
                    </button>
                  ) : subscription.status === "paused" ? (
                    <button
                      disabled={busy}
                      onClick={() =>
                        onPrompt(`恢复${subscription.merchant}自动续费`)
                      }
                      type="button"
                    >
                      恢复
                    </button>
                  ) : null}
                  {subscription.status !== "cancelled" ? (
                    <button
                      className="danger-text"
                      disabled={busy}
                      onClick={() =>
                        onPrompt(`取消${subscription.merchant}自动续费`)
                      }
                      type="button"
                    >
                      取消
                    </button>
                  ) : null}
                </div>
                <div className="reminder-preference">
                  <label htmlFor={`reminder-${subscription.id}`}>
                    提前提醒
                  </label>
                  <select
                    disabled={reminderBusy}
                    id={`reminder-${subscription.id}`}
                    onChange={(event) =>
                      void updateReminder(
                        subscription,
                        Number(event.target.value),
                      )
                    }
                    value={subscription.reminder_days_before}
                  >
                    <option value={0}>当天</option>
                    <option value={1}>1 天</option>
                    <option value={3}>3 天</option>
                    <option value={7}>7 天</option>
                    <option value={14}>14 天</option>
                  </select>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="page-empty">暂时没有识别到周期扣费。</p>
        )}
      </section>
    </div>
  );
}
