import { useCallback, useEffect, useState, type FormEvent } from "react";

import { apiClient } from "../api/client";
import type {
  AccountBalanceListResponse,
  PayeeListResponse,
  TransferDestinationListResponse,
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
  destinations: TransferDestinationListResponse;
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
  const [showPayeeForm, setShowPayeeForm] = useState(false);
  const [payeeName, setPayeeName] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [savingPayee, setSavingPayee] = useState(false);
  const [payeeError, setPayeeError] = useState<string | null>(null);
  const [payeeNotice, setPayeeNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [accounts, payees, destinations, transfers, splits] =
        await Promise.all([
          apiClient.readAccounts(),
          apiClient.readPayees(),
          apiClient.readTransferDestinations(),
          apiClient.readTransfers(),
          apiClient.readSplits(),
        ]);
      setData({ accounts, payees, destinations, transfers, splits });
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "暂时无法读取转账信息。",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  async function savePayee(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedDestinationId =
      destinationId || data?.destinations.items[0]?.id || "";
    if (!data || savingPayee || !payeeName.trim() || !selectedDestinationId)
      return;
    const previousIds = new Set(data.payees.items.map((item) => item.id));
    setSavingPayee(true);
    setPayeeError(null);
    setPayeeNotice(null);
    try {
      await apiClient.createPayee({
        display_name: payeeName.trim(),
        destination_account_id: selectedDestinationId,
      });
      setPayeeNotice("收款人已保存，可以继续发起转账。");
      setPayeeName("");
      setShowPayeeForm(false);
      await load();
    } catch (caught) {
      // Payee creation has no server idempotency key yet. Re-read first if the
      // response was lost; never blindly submit another create request.
      try {
        const latest = await apiClient.readPayees();
        setData((current) =>
          current ? { ...current, payees: latest } : current,
        );
        const wasCreated = latest.items.some(
          (item) =>
            !previousIds.has(item.id) &&
            item.display_name.trim() === payeeName.trim() &&
            item.destination_account_id === selectedDestinationId,
        );
        if (wasCreated) {
          setPayeeNotice("收款人已保存，可以继续发起转账。");
          setPayeeName("");
          setShowPayeeForm(false);
          return;
        }
      } catch {
        // Keep the form open so the user can inspect it after connectivity returns.
      }
      setPayeeError(
        caught instanceof Error ? caught.message : "暂时无法保存收款人。",
      );
    } finally {
      setSavingPayee(false);
    }
  }

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
        onAction={() => onPrompt("我要发起一笔转账，请先询问收款人和金额")}
        title="转账与分账"
      />

      <div className="transfer-hero">
        <div>
          <p className="transfer-balance-label">可用余额</p>
          <h2>
            {loading ? (
              <SkeletonLine width="180px" />
            ) : (
              money(totalBalance, currency)
            )}
          </h2>
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
            <h2>账户余额</h2>
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
            <h2>收款人</h2>
            <button
              className="payee-add-toggle"
              disabled={busy}
              onClick={() => {
                setShowPayeeForm((open) => !open);
                setPayeeError(null);
                setPayeeNotice(null);
              }}
              type="button"
            >
              {showPayeeForm ? "收起" : "添加收款人"}
            </button>
          </header>
          {showPayeeForm ? (
            <form
              className="payee-form"
              onSubmit={(event: FormEvent<HTMLFormElement>) =>
                void savePayee(event)
              }
            >
              <label>
                收款人姓名
                <input
                  autoComplete="off"
                  maxLength={80}
                  onChange={(event) => setPayeeName(event.target.value)}
                  required
                  value={payeeName}
                />
              </label>
              <label>
                收款账户
                <select
                  onChange={(event) => setDestinationId(event.target.value)}
                  required
                  value={destinationId || data?.destinations.items[0]?.id || ""}
                >
                  {data?.destinations.items.map((destination) => (
                    <option key={destination.id} value={destination.id}>
                      {customerText(destination.label)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="payee-save-button"
                disabled={
                  savingPayee ||
                  busy ||
                  !payeeName.trim() ||
                  data?.destinations.items.length === 0
                }
                type="submit"
              >
                {savingPayee ? "正在保存…" : "保存收款人"}
              </button>
              {data?.destinations.items.length === 0 ? (
                <p className="payee-form-note">当前没有可选的收款账户。</p>
              ) : null}
              {payeeError ? (
                <p className="payee-form-error" role="alert">
                  {payeeError}
                </p>
              ) : null}
            </form>
          ) : null}
          {payeeNotice ? (
            <p className="payee-form-note" role="status">
              {payeeNotice}
            </p>
          ) : null}
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
          <h2>转账记录</h2>
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
                    {" · "}
                    {transfer.status === "executed"
                      ? "已完成"
                      : transfer.status === "scheduled"
                        ? "待执行"
                        : transfer.status === "cancelled"
                          ? "已取消"
                          : "等待确认"}
                    {transfer.remark ? ` · 备注：${transfer.remark}` : ""}
                  </small>
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
          <h2>AA 分账</h2>
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
                  <small>
                    {split.participant_count} 人参与 ·{" "}
                    {split.status === "open"
                      ? "待收款"
                      : split.status === "settled"
                        ? "已结清"
                        : split.status === "cancelled"
                          ? "已取消"
                          : "等待确认"}
                  </small>
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
