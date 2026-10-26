import { useCallback, useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type {
  AccountBalanceListResponse,
  PayeeListResponse,
  SplitBillListResponse,
  TransferListResponse,
} from "../api/client";
import { AppIcon } from "../components/AppIcon";
import { PageHeader } from "../components/PageHeader";
import { customerText } from "../userFacing";
import { SkeletonLine, SkeletonRows } from "../components/Skeleton";

function money(value: number, currency = "CNY"): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value / 100);
}

function dateLabel(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

type TransferData = {
  accounts: AccountBalanceListResponse;
  payees: PayeeListResponse;
  transfers: TransferListResponse;
  splits: SplitBillListResponse;
};

export function TransfersPage({
  busy,
  onPrompt,
}: {
  busy: boolean;
  onPrompt: (prompt: string) => void;
}) {
  const [data, setData] = useState<TransferData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [accounts, payees, transfers, splits] = await Promise.all([
        apiClient.readAccounts(),
        apiClient.readPayees(),
        apiClient.readTransfers(),
        apiClient.readSplits(),
      ]);
      setData({ accounts, payees, transfers, splits });
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "暂时无法读取转账信息。",
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
  }, [load]);

  const totalBalance =
    data?.accounts.items.reduce(
      (total, account) => total + account.balance_minor,
      0,
    ) ?? 0;
  const currency = data?.accounts.items[0]?.currency ?? "CNY";

  return (
    <div className="page-stack">
      <PageHeader
        actionLabel="发起转账"
        busy={busy}
        description="查看余额与收款人，所有资金变化在明确确认后由服务端执行。"
        eyebrow="账户资金"
        onAction={() => onPrompt("我要发起一笔转账，请先询问收款人和金额")}
        title="转账与分账"
      />

      <div className="transfer-hero">
        <div>
          <p className="eyebrow">账户余额</p>
          <h2>
            {loading ? (
              <SkeletonLine width="180px" />
            ) : (
              money(totalBalance, currency)
            )}
          </h2>
          <span>
            {loading ? (
              <SkeletonLine width="72px" />
            ) : (
              `${data?.accounts.items.length ?? 0} 个账户`
            )}
          </span>
        </div>
        <div className="transfer-hero-actions">
          <button
            disabled={busy}
            onClick={() => onPrompt("我要发起一笔转账，请先询问收款人和金额")}
            type="button"
          >
            <AppIcon name="transfer" size={18} />
            发起转账
          </button>
          <button
            disabled={busy}
            onClick={() => onPrompt("帮我创建一个 AA 分账，请询问总额和参与人")}
            type="button"
          >
            <AppIcon name="overview" size={18} />
            创建分账
          </button>
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

      <div className="transfer-columns">
        <section className="data-panel">
          <header>
            <div>
              <p className="eyebrow">账户</p>
              <h2>账户余额</h2>
            </div>
          </header>
          {loading ? (
            <SkeletonRows count={2} />
          ) : (
            <div className="data-table">
              {data?.accounts.items.map((account) => (
                <div className="data-row static" key={account.id}>
                  <span className="transaction-icon">
                    <AppIcon name="overview" size={17} />
                  </span>
                  <span className="data-row-main">
                    <strong>{customerText(account.label)}</strong>
                    <small>个人账户</small>
                  </span>
                  <strong>
                    {money(account.balance_minor, account.currency)}
                  </strong>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="data-panel">
          <header>
            <div>
              <p className="eyebrow">收款人</p>
              <h2>最近收款人</h2>
            </div>
            <span>{data?.payees.items.length ?? 0} 人</span>
          </header>
          {loading ? (
            <SkeletonRows count={2} />
          ) : (
            <div className="payee-grid">
              {data?.payees.items.map((payee) => (
                <button
                  disabled={busy}
                  key={payee.id}
                  onClick={() =>
                    onPrompt(`给${payee.display_name}发起一笔转账，请询问金额`)
                  }
                  type="button"
                >
                  <span>{payee.display_name.slice(0, 1)}</span>
                  <strong>{payee.display_name}</strong>
                  <small>
                    {customerText(payee.destination_account_label)}
                    {payee.phone_masked ? ` · ${payee.phone_masked}` : ""}
                  </small>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="data-panel">
        <header>
          <div>
            <p className="eyebrow">转账记录</p>
            <h2>转账记录</h2>
          </div>
          <span>{data?.transfers.items.length ?? 0} 笔</span>
        </header>
        {loading ? (
          <SkeletonRows count={4} />
        ) : data?.transfers.items.length ? (
          <div className="data-table">
            {data.transfers.items.map((transfer) => (
              <div className="data-row static" key={transfer.id}>
                <span className="transaction-icon">
                  <AppIcon name="transfer" size={17} />
                </span>
                <span className="data-row-main">
                  <strong>{transfer.payee_name}</strong>
                  <small>
                    {customerText(transfer.source_account_label)} ·{" "}
                    {dateLabel(transfer.scheduled_at ?? transfer.executed_at)}
                    {transfer.remark ? ` · 备注：${transfer.remark}` : ""}
                  </small>
                </span>
                <span className={"order-status status-" + transfer.status}>
                  {transfer.status === "executed"
                    ? "已完成"
                    : transfer.status === "scheduled"
                      ? "待执行"
                      : transfer.status === "cancelled"
                        ? "已取消"
                        : "等待确认"}
                </span>
                <strong>
                  {money(transfer.amount_minor, transfer.currency)}
                </strong>
              </div>
            ))}
          </div>
        ) : (
          <p className="page-empty">暂无转账记录。</p>
        )}
      </section>

      <section className="data-panel">
        <header>
          <div>
            <p className="eyebrow">AA 分账</p>
            <h2>AA 分账</h2>
          </div>
          <span>{data?.splits.items.length ?? 0} 笔</span>
        </header>
        {loading ? (
          <SkeletonRows count={3} />
        ) : data?.splits.items.length ? (
          <div className="data-table">
            {data.splits.items.map((split) => (
              <div className="data-row static" key={split.id}>
                <span className="transaction-icon">
                  <AppIcon name="overview" size={17} />
                </span>
                <span className="data-row-main">
                  <strong>{split.title}</strong>
                  <small>{split.participant_count} 人参与</small>
                </span>
                <span className={"order-status status-" + split.status}>
                  {split.status === "open"
                    ? "待收款"
                    : split.status === "settled"
                      ? "已结清"
                      : split.status === "cancelled"
                        ? "已取消"
                        : "等待确认"}
                </span>
                <strong>
                  {money(split.total_amount_minor, split.currency)}
                </strong>
              </div>
            ))}
          </div>
        ) : (
          <p className="page-empty">暂无 AA 分账。</p>
        )}
      </section>
    </div>
  );
}
