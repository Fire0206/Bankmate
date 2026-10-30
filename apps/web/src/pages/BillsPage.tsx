import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { apiClient } from "../api/client";
import { brand } from "../brand";
import type {
  BillSummaryResponse,
  TransactionPageResponse,
} from "../api/client";
import { AppIcon } from "../components/AppIcon";
import { CashflowChart } from "../components/CashflowChart";
import { MerchantMark } from "../components/MerchantMark";
import { PageHeader } from "../components/PageHeader";
import { SideDrawer } from "../components/SideDrawer";
import { SkeletonLine, SkeletonRows } from "../components/Skeleton";
import { customerText, transactionDescription } from "../userFacing";

type Transaction = TransactionPageResponse["items"][number];
type Filters = {
  month: string;
  category: string;
  merchant: string;
  direction: "all" | "income" | "expense";
};

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(month: string, delta: number): string {
  const [year, monthNumber] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, monthNumber - 1 + delta, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function money(value: number, currency = "CNY"): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value / 100);
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function FilterModal({
  filters,
  categories,
  onApply,
  onClose,
}: {
  filters: Filters;
  categories: BillSummaryResponse["categories"];
  onApply: (filters: Filters) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(filters);
  const months = useMemo(
    () =>
      Array.from({ length: 6 }, (_, index) =>
        shiftMonth(filters.month, -index),
      ),
    [filters.month],
  );

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        aria-modal="true"
        className="modal-dialog filter-dialog"
        role="dialog"
      >
        <header className="filter-dialog-header">
          <div>
            <p className="eyebrow">筛选条件</p>
            <h2>筛选账单</h2>
          </div>
          <button
            aria-label="关闭筛选"
            className="modal-close modal-close-inline"
            onClick={onClose}
            type="button"
          >
            <AppIcon name="close" size={18} />
          </button>
        </header>
        <div className="filter-fields">
          <label>
            <span>月份</span>
            <select
              onChange={(event) =>
                setDraft((value) => ({ ...value, month: event.target.value }))
              }
              value={draft.month}
            >
              {months.map((month) => (
                <option key={month} value={month}>
                  {month.replace("-", " 年 ")} 月
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>消费类别</span>
            <select
              onChange={(event) =>
                setDraft((value) => ({
                  ...value,
                  category: event.target.value,
                }))
              }
              value={draft.category}
            >
              <option value="">全部类别</option>
              {categories.map((category) => (
                <option key={category.category} value={category.category}>
                  {category.category}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>收支方向</span>
            <select
              onChange={(event) =>
                setDraft((value) => ({
                  ...value,
                  direction: event.target.value as Filters["direction"],
                }))
              }
              value={draft.direction}
            >
              <option value="all">全部交易</option>
              <option value="expense">只看支出</option>
              <option value="income">只看收入</option>
            </select>
          </label>
          <label>
            <span>商户关键词</span>
            <input
              maxLength={120}
              onChange={(event) =>
                setDraft((value) => ({
                  ...value,
                  merchant: event.target.value,
                }))
              }
              placeholder="例如：腾讯视频"
              value={draft.merchant}
            />
          </label>
        </div>
        <div className="filter-actions">
          <button
            className="button button-secondary"
            onClick={() =>
              setDraft({
                ...draft,
                category: "",
                merchant: "",
                direction: "all",
              })
            }
            type="button"
          >
            清除条件
          </button>
          <button
            className="button button-primary"
            onClick={() => onApply(draft)}
            type="button"
          >
            应用筛选
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function TransactionDrawer({
  transaction,
  onClose,
  onPrompt,
}: {
  transaction: Transaction;
  onClose: () => void;
  onPrompt: (prompt: string) => void;
}) {
  return (
    <SideDrawer
      onClose={onClose}
      subtitle="Transaction detail"
      title={transaction.merchant}
    >
      <div className="transaction-detail">
        <div className="transaction-detail-amount">
          <span>{transaction.direction === "income" ? "收入" : "支出"}</span>
          <strong>
            {transaction.direction === "income" ? "+" : "−"}
            {money(transaction.amount_minor, transaction.currency)}
          </strong>
          <small>{dateLabel(transaction.occurred_at)}</small>
        </div>
        <dl>
          <div>
            <dt>交易类别</dt>
            <dd>{transaction.category}</dd>
          </div>
          <div>
            <dt>交易说明</dt>
            <dd>
              {transactionDescription(
                transaction.description,
                transaction.category,
                transaction.direction,
              )}
            </dd>
          </div>
          <div>
            <dt>来源卡片</dt>
            <dd>
              {transaction.source_card_suffix
                ? `尾号 ${transaction.source_card_suffix}`
                : "账户交易"}
            </dd>
          </div>
          <div>
            <dt>交易编号</dt>
            <dd>
              <code>{transaction.id}</code>
            </dd>
          </div>
        </dl>
        {transaction.anomaly_reason ? (
          <div className="transaction-risk-note">
            <span>
              <AppIcon name="info" size={16} />
              为什么出现提示
            </span>
            <p>{customerText(transaction.anomaly_reason)}</p>
            <small>账单规则提醒，仅供核对，不代表欺诈结论。</small>
          </div>
        ) : null}
        <div className="drawer-actions">
          <button
            className="button button-primary"
            onClick={() => {
              onClose();
              onPrompt(
                transaction.anomaly_reason
                  ? `核对${transaction.merchant}的账单提示${transaction.source_card_suffix ? `，银行卡尾号 ${transaction.source_card_suffix}` : ""}`
                  : `帮我查看 ${transaction.merchant} 这笔交易并说明影响`,
              );
            }}
            type="button"
          >
            询问 {brand.name}
          </button>
          <button
            className="button button-secondary"
            onClick={onClose}
            type="button"
          >
            返回账单
          </button>
        </div>
      </div>
    </SideDrawer>
  );
}

export function BillsPage({
  busy,
  onPrompt,
}: {
  busy: boolean;
  onPrompt: (prompt: string) => void;
}) {
  const [filters, setFilters] = useState<Filters>({
    month: currentMonth(),
    category: "",
    merchant: "",
    direction: "all",
  });
  const [summary, setSummary] = useState<BillSummaryResponse | null>(null);
  const [transactions, setTransactions] =
    useState<TransactionPageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [selected, setSelected] = useState<Transaction | null>(null);

  const load = useCallback(async (currentFilters: Filters) => {
    try {
      const [nextSummary, nextTransactions] = await Promise.all([
        apiClient.readBillSummary(
          currentFilters.month,
          currentFilters.category || undefined,
        ),
        apiClient.readTransactions({
          month: currentFilters.month,
          category: currentFilters.category || undefined,
          merchant: currentFilters.merchant || undefined,
          direction:
            currentFilters.direction === "all"
              ? undefined
              : currentFilters.direction,
          limit: 100,
        }),
      ]);
      setSummary(nextSummary);
      setTransactions(nextTransactions);
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "暂时无法读取账单数据。",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load(filters);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [filters, load]);

  const categoryOptions = summary?.categories ?? [];

  return (
    <div className="page-stack bills-page">
      <PageHeader
        actionLabel="询问账单"
        busy={busy}
        onAction={() => onPrompt("分析我本月的账单和异常消费")}
        title="账单分析"
      />

      {error ? (
        <div className="page-error" role="alert">
          {error}
          <button
            onClick={() => {
              setLoading(true);
              void load(filters);
            }}
            type="button"
          >
            重新读取
          </button>
        </div>
      ) : null}

      <section className="bills-workspace">
        <header className="bills-workspace-toolbar">
          <div className="active-filters">
            <strong>
              {(summary?.month ?? filters.month).replace("-", " 年 ")} 月
            </strong>
            {filters.category ? <span>{filters.category}</span> : null}
            {filters.direction !== "all" ? (
              <span>
                {filters.direction === "expense" ? "仅支出" : "仅收入"}
              </span>
            ) : null}
            {filters.merchant ? <span>{filters.merchant}</span> : null}
          </div>
          <button
            className="filter-button"
            onClick={() => setFilterOpen(true)}
            type="button"
          >
            <AppIcon name="menu" size={16} />
            筛选
          </button>
        </header>

        <div className="bills-overview">
          <section className="bills-trend">
            <header>
              <h2>收支趋势</h2>
              <div aria-label="图表说明" className="cashflow-legend">
                <span>
                  <i className="cashflow-legend-income" />
                  收入
                </span>
                <span>
                  <i className="cashflow-legend-expense" />
                  支出
                </span>
              </div>
            </header>
            <div className="bills-kpis">
              <div>
                <span>收入</span>
                <strong>
                  {loading ? (
                    <SkeletonLine width="86px" />
                  ) : (
                    money(summary?.income_minor ?? 0)
                  )}
                </strong>
              </div>
              <div>
                <span>支出</span>
                <strong>
                  {loading ? (
                    <SkeletonLine width="86px" />
                  ) : (
                    money(summary?.expense_minor ?? 0)
                  )}
                </strong>
              </div>
              <div>
                <span>净现金流</span>
                <strong>
                  {loading ? (
                    <SkeletonLine width="86px" />
                  ) : (
                    money(summary?.net_minor ?? 0)
                  )}
                </strong>
              </div>
            </div>
            {loading ? (
              <div aria-hidden="true" className="chart-skeleton">
                {Array.from({ length: 6 }, (_, index) => (
                  <span key={index} />
                ))}
              </div>
            ) : summary?.trends.length ? (
              <CashflowChart
                currencyCode={summary.currency}
                trends={summary.trends}
              />
            ) : (
              <div className="page-empty">暂无可视化数据</div>
            )}
          </section>

          <section className="bills-categories">
            <header>
              <h2>消费类别</h2>
            </header>
            {loading ? (
              <SkeletonRows count={6} lead={false} />
            ) : categoryOptions.length ? (
              <div className="category-list">
                {categoryOptions.map((category) => {
                  return (
                    <button
                      aria-pressed={filters.category === category.category}
                      className={
                        "category-row" +
                        (filters.category === category.category
                          ? " is-selected"
                          : "")
                      }
                      key={category.category}
                      onClick={() =>
                        setFilters((value) => ({
                          ...value,
                          category:
                            value.category === category.category
                              ? ""
                              : category.category,
                        }))
                      }
                      type="button"
                    >
                      <MerchantMark
                        category={category.category}
                        className="category-merchant-mark"
                        merchant=""
                      />
                      <span>
                        <strong>{category.category}</strong>
                      </span>
                      <strong>{money(category.amount_minor)}</strong>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="page-empty">当前条件下没有消费。</p>
            )}
          </section>
        </div>

        <section className="bills-transactions">
          <header>
            <h2>交易明细</h2>
          </header>
          {loading ? (
            <SkeletonRows count={7} />
          ) : transactions?.items.length ? (
            <div className="data-table transaction-table">
              {transactions.items.map((transaction) => (
                <button
                  className={
                    "data-row transaction-data-row" +
                    (transaction.anomaly_reason ? " has-anomaly" : "")
                  }
                  key={transaction.id}
                  onClick={() => setSelected(transaction)}
                  type="button"
                >
                  <MerchantMark
                    category={transaction.category}
                    merchant={transaction.merchant}
                  />
                  <span className="data-row-main">
                    <strong>{transaction.merchant}</strong>
                    <small>
                      {transaction.category} ·{" "}
                      {dateLabel(transaction.occurred_at)}
                    </small>
                  </span>
                  {transaction.anomaly_reason ? (
                    <span className="risk-badge">需复核</span>
                  ) : null}
                  <strong
                    className={
                      transaction.direction === "income" ? "amount-income" : ""
                    }
                  >
                    {transaction.direction === "income" ? "+" : "−"}
                    {money(transaction.amount_minor, transaction.currency)}
                  </strong>
                  <AppIcon name="arrow-right" size={16} />
                </button>
              ))}
            </div>
          ) : (
            <p className="page-empty">当前筛选没有交易。</p>
          )}
        </section>
      </section>

      {filterOpen ? (
        <FilterModal
          categories={categoryOptions}
          filters={filters}
          onApply={(next) => {
            setLoading(true);
            setFilters(next);
            setFilterOpen(false);
          }}
          onClose={() => setFilterOpen(false)}
        />
      ) : null}
      {selected ? (
        <TransactionDrawer
          onClose={() => setSelected(null)}
          onPrompt={onPrompt}
          transaction={selected}
        />
      ) : null}
    </div>
  );
}
