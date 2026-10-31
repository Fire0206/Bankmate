import { useCallback, useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type {
  AccountBalanceListResponse,
  BillSummaryResponse,
  CardListResponse,
  DemoSessionResponse,
  SubscriptionListResponse,
} from "../api/client";
import { AppIcon } from "./AppIcon";
import { CashflowChart } from "./CashflowChart";
import { SkeletonLine } from "./Skeleton";
import { customerName } from "../userFacing";

type OverviewData = {
  accounts: AccountBalanceListResponse;
  bills: BillSummaryResponse;
  subscriptions: SubscriptionListResponse;
};

function currency(
  valueMinor: number | null | undefined,
  currencyCode = "CNY",
): string {
  if (valueMinor === null || valueMinor === undefined) return "—";
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: currencyCode,
    maximumFractionDigits: 2,
  }).format(valueMinor / 100);
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 12) return "早上好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

function monthLabel(month: string): string {
  const [, monthNumber] = month.split("-").map(Number);
  return `${monthNumber} 月`;
}

export function WorkspaceOverview({
  session,
  cards,
  refreshKey,
  busy,
  onPrompt,
  onOpenCards,
}: {
  session: DemoSessionResponse | null;
  cards: CardListResponse["items"];
  refreshKey: string;
  busy: boolean;
  onPrompt: (prompt: string) => void;
  onOpenCards: () => void;
}) {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [accounts, bills, subscriptions] = await Promise.all([
        apiClient.readAccounts(),
        apiClient.readBillSummary(),
        apiClient.readSubscriptions(),
      ]);
      setData({ accounts, bills, subscriptions });
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "暂时无法读取财务总览。",
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

  const displayName = customerName(session?.display_name);
  const currencyCode =
    data?.accounts.items[0]?.currency ?? data?.bills.currency ?? "CNY";
  const totalBalance =
    data?.accounts.items.reduce(
      (total, account) => total + account.balance_minor,
      0,
    ) ?? null;
  const activeSubscriptions =
    data?.subscriptions.items.filter((item) => item.status === "active") ?? [];
  const frozenCards = cards.filter((card) => card.status === "frozen").length;
  const anomalies = data?.bills.anomalies ?? [];
  const leadingAnomaly = anomalies[0] ?? null;
  const anomalyPrompt = leadingAnomaly
    ? `处理异常扣款：本月 ${leadingAnomaly.merchant} 出现重复扣费，卡片尾号 ${leadingAnomaly.source_card_suffix ?? "1042"}。请先展示证据，再提出冻结操作。`
    : "处理异常扣款，请先检查本月重复扣费并展示证据";

  return (
    <section aria-labelledby="overview-title" className="workspace-overview">
      <article className="overview-intro">
        <div className="overview-eyebrow">
          <span className="overview-status-dot" />
          账户总览
        </div>
        <h1 id="overview-title">
          {greeting()}，{displayName}
        </h1>
        <p className="overview-lede">
          说出你要办理的业务，确认后即可继续处理。
        </p>

        <div className="overview-actions">
          <button
            className="overview-action overview-action-primary"
            disabled={busy}
            onClick={() => onPrompt(anomalyPrompt)}
            type="button"
          >
            <span className="overview-action-icon">
              <AppIcon name="bill" size={18} />
            </span>
            <span>
              <strong>调查异常消费</strong>
              <small>从证据开始，不直接操作资金</small>
            </span>
            <AppIcon name="arrow-right" size={17} />
          </button>
          <button
            className="overview-action"
            disabled={busy}
            onClick={() =>
              onPrompt(
                data
                  ? `分析我 ${data.bills.month} 的账单，并解释异常消费`
                  : "分析我本月的账单",
              )
            }
            type="button"
          >
            <span className="overview-action-icon">
              <AppIcon name="wealth" size={18} />
            </span>
            <span>
              <strong>看懂本月账单</strong>
              <small>趋势、分类与异常依据</small>
            </span>
            <AppIcon name="arrow-right" size={17} />
          </button>
        </div>

        <div
          className={
            "overview-risk " +
            (anomalies.length > 0 ? "overview-risk-active" : "")
          }
        >
          <span className="overview-risk-icon">
            <AppIcon name={anomalies.length > 0 ? "info" : "check"} size={17} />
          </span>
          <span>
            <strong>
              {loading
                ? "正在核对本月交易"
                : error
                  ? "财务摘要暂不可用"
                  : anomalies.length > 0
                    ? `发现 ${anomalies.length} 笔待复核交易`
                    : "本月没有需要核对的交易"}
            </strong>
            <small>
              {error
                ? "请重新读取账户与账单数据。"
                : leadingAnomaly
                  ? `${leadingAnomaly.merchant} · ${currency(leadingAnomaly.amount_minor, leadingAnomaly.currency)} · 根据账单记录提醒，请核对交易`
                  : "提醒依据为账单记录。"}
            </small>
          </span>
          {anomalies.length > 0 ? (
            <button
              disabled={busy}
              onClick={() => onPrompt(anomalyPrompt)}
              type="button"
            >
              开始核对
            </button>
          ) : null}
        </div>
      </article>

      <article className="overview-cashflow">
        <header>
          <div>
            <p className="overview-card-kicker">
              {data ? monthLabel(data.bills.month) : "本月"}现金流
            </p>
            <h2>
              {loading ? (
                <SkeletonLine className="overview-value-skeleton" width="68%" />
              ) : (
                currency(data?.bills.net_minor, currencyCode)
              )}
            </h2>
            <p>净现金流 · 收入减支出</p>
          </div>
          <div className="cashflow-legend">
            <span>
              <i className="legend-income" />
              收入
            </span>
            <span>
              <i className="legend-expense" />
              支出
            </span>
          </div>
        </header>
        <div className="cashflow-summary">
          <span>
            收入
            <strong>
              {loading ? (
                <SkeletonLine width="82px" />
              ) : (
                currency(data?.bills.income_minor, currencyCode)
              )}
            </strong>
          </span>
          <span>
            支出
            <strong>
              {loading ? (
                <SkeletonLine width="82px" />
              ) : (
                currency(data?.bills.expense_minor, currencyCode)
              )}
            </strong>
          </span>
        </div>
        {loading ? (
          <div aria-hidden="true" className="chart-skeleton">
            {Array.from({ length: 6 }, (_, index) => (
              <span key={index} />
            ))}
          </div>
        ) : data?.bills.trends.length ? (
          <CashflowChart
            expenseMinor={data.bills.expense_minor}
            incomeMinor={data.bills.income_minor}
            trends={data.bills.trends}
          />
        ) : (
          <div className="overview-chart-empty">暂无可展示的现金流趋势</div>
        )}
      </article>

      <div className="overview-metrics">
        <button className="overview-metric" onClick={onOpenCards} type="button">
          <span className="overview-metric-icon">
            <AppIcon name="overview" size={18} />
          </span>
          <span>
            <small>可用余额</small>
            <strong>
              {loading ? (
                <SkeletonLine width="94px" />
              ) : (
                currency(totalBalance, currencyCode)
              )}
            </strong>
            <em>{data?.accounts.items.length ?? 0} 个账户</em>
          </span>
        </button>
        <button
          className="overview-metric"
          disabled={busy}
          onClick={() => onPrompt("我这个月花了多少钱，主要花在哪些类别")}
          type="button"
        >
          <span className="overview-metric-icon overview-metric-warm">
            <AppIcon name="bill" size={18} />
          </span>
          <span>
            <small>本月支出</small>
            <strong>
              {loading ? (
                <SkeletonLine width="94px" />
              ) : (
                currency(data?.bills.expense_minor, currencyCode)
              )}
            </strong>
            <em>{data?.bills.categories.length ?? 0} 个消费类别</em>
          </span>
        </button>
        <button
          className="overview-metric"
          disabled={busy}
          onClick={() => onPrompt("看看我有哪些自动扣费，下一次什么时候扣款")}
          type="button"
        >
          <span className="overview-metric-icon overview-metric-blue">
            <AppIcon name="subscriptions" size={18} />
          </span>
          <span>
            <small>每月自动扣费</small>
            <strong>
              {loading ? (
                <SkeletonLine width="82px" />
              ) : (
                currency(
                  data?.subscriptions.monthly_total_minor,
                  data?.subscriptions.currency ?? currencyCode,
                )
              )}
            </strong>
            <em>{activeSubscriptions.length} 项正在生效</em>
          </span>
        </button>
        <button className="overview-metric" onClick={onOpenCards} type="button">
          <span className="overview-metric-icon overview-metric-red">
            <AppIcon name="cards" size={18} />
          </span>
          <span>
            <small>卡片状态</small>
            <strong>
              {loading ? (
                <SkeletonLine width="82px" />
              ) : (
                `${cards.length - frozenCards} 张可用`
              )}
            </strong>
            <em>{frozenCards} 张已冻结</em>
          </span>
        </button>
      </div>

      {error ? (
        <div className="overview-error" role="alert">
          <span>{error}</span>
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
    </section>
  );
}
