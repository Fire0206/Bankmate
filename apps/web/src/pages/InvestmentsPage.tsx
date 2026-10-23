import { useCallback, useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type {
  InvestmentOrderListResponse,
  InvestmentPortfolioResponse,
  InvestmentProductListResponse,
  RiskProfileResponse,
} from "../api/client";
import { AppIcon } from "../components/AppIcon";
import { PageHeader } from "../components/PageHeader";
import { RiskAssessmentForm } from "../components/RiskAssessmentForm";
import { SkeletonLine, SkeletonRows } from "../components/Skeleton";

type InvestmentData = {
  profile: RiskProfileResponse;
  products: InvestmentProductListResponse;
  portfolio: InvestmentPortfolioResponse;
  orders: InvestmentOrderListResponse;
};

function money(value: number, currency = "CNY"): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value / 100);
}

export function InvestmentsPage({
  busy,
  onPrompt,
}: {
  busy: boolean;
  onPrompt: (prompt: string) => void;
}) {
  const [data, setData] = useState<InvestmentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [profile, products, portfolio, orders] = await Promise.all([
        apiClient.readRiskProfile(),
        apiClient.readInvestmentProducts(),
        apiClient.readInvestmentPortfolio(),
        apiClient.readInvestmentOrders(),
      ]);
      setData({ profile, products, portfolio, orders });
      setError(null);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "暂时无法读取理财信息。",
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

  return (
    <div className="page-stack">
      <PageHeader
        actionLabel="分析理财配置"
        busy={busy}
        description="所有产品、收益和持仓均为模拟数据；申购与赎回必须经过适当性和服务端确认。"
        eyebrow="Wealth simulation"
        onAction={() =>
          onPrompt("分析我的模拟理财持仓，并给出符合我风险等级的配置建议")
        }
        title="模拟理财"
      />

      <div className="portfolio-hero">
        <div>
          <p className="eyebrow">Total assets</p>
          <h2>
            {loading ? (
              <SkeletonLine width="180px" />
            ) : (
              money(
                data?.portfolio.total_assets_minor ?? 0,
                data?.portfolio.currency,
              )
            )}
          </h2>
          <span>
            风险等级{" "}
            {data?.profile.risk_label ?? `R${data?.profile.risk_level ?? "—"}`}
          </span>
        </div>
        <div className="portfolio-breakdown">
          <div>
            <span>现金</span>
            <strong>
              {money(
                data?.portfolio.cash_balance_minor ?? 0,
                data?.portfolio.currency,
              )}
            </strong>
          </div>
          <div>
            <span>持仓</span>
            <strong>
              {money(
                data?.portfolio.invested_value_minor ?? 0,
                data?.portfolio.currency,
              )}
            </strong>
          </div>
          <div>
            <span>估算盈亏</span>
            <strong
              className={
                (data?.portfolio.estimated_gain_minor ?? 0) >= 0
                  ? "amount-income"
                  : ""
              }
            >
              {money(
                data?.portfolio.estimated_gain_minor ?? 0,
                data?.portfolio.currency,
              )}
            </strong>
          </div>
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

      <section className="data-panel">
        <header>
          <div>
            <p className="eyebrow">Products</p>
            <h2>适合的模拟产品</h2>
          </div>
          <span>{data?.products.items.length ?? 0} 个</span>
        </header>
        {loading ? (
          <div className="product-grid">
            <div className="product-card product-card-skeleton" />
            <div className="product-card product-card-skeleton" />
            <div className="product-card product-card-skeleton" />
          </div>
        ) : (
          <div className="product-grid">
            {data?.products.items.map((product) => (
              <article
                className={
                  "product-card" + (product.suitable ? " is-suitable" : "")
                }
                key={product.id}
              >
                <header>
                  <span>R{product.risk_level}</span>
                  <small>{product.category}</small>
                </header>
                <h3>{product.name}</h3>
                <p>{product.description}</p>
                <div>
                  <span>
                    参考年化
                    <strong>
                      {(product.annual_yield_bps / 100).toFixed(2)}%
                    </strong>
                  </span>
                  <span>
                    起购金额
                    <strong>
                      {money(product.minimum_amount_minor, product.currency)}
                    </strong>
                  </span>
                </div>
                <p className="product-fit">
                  {product.suitable
                    ? "符合当前模拟风险等级"
                    : "超出当前模拟风险等级"}
                </p>
                <button
                  disabled={busy || !product.suitable}
                  onClick={() =>
                    onPrompt(
                      `了解并申购${product.name}，金额为起购金额${money(product.minimum_amount_minor, product.currency)}`,
                    )
                  }
                  type="button"
                >
                  {product.suitable ? "咨询申购" : "风险不匹配"}
                </button>
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="transfer-columns">
        <section className="data-panel">
          <header>
            <div>
              <p className="eyebrow">Holdings</p>
              <h2>当前持仓</h2>
            </div>
          </header>
          {loading ? (
            <SkeletonRows count={3} />
          ) : data?.portfolio.holdings.length ? (
            <div className="data-table">
              {data.portfolio.holdings.map((holding) => (
                <div className="data-row static" key={holding.id}>
                  <span className="transaction-icon">
                    <AppIcon name="wealth" size={17} />
                  </span>
                  <span className="data-row-main">
                    <strong>{holding.product_name}</strong>
                    <small>
                      {(holding.units_micros / 1_000_000).toLocaleString(
                        "zh-CN",
                      )}{" "}
                      份 · 当前净值{" "}
                      {money(holding.current_price_minor, holding.currency)}
                    </small>
                  </span>
                  <strong>
                    {money(
                      holding.current_value_minor,
                      data.portfolio.currency,
                    )}
                  </strong>
                </div>
              ))}
            </div>
          ) : (
            <p className="page-empty">暂无模拟持仓。</p>
          )}
        </section>

        <section className="data-panel">
          <header>
            <div>
              <p className="eyebrow">Orders</p>
              <h2>理财记录</h2>
            </div>
          </header>
          {loading ? (
            <SkeletonRows count={3} />
          ) : data?.orders.items.length ? (
            <div className="data-table">
              {data.orders.items.map((order) => (
                <div className="data-row static" key={order.id}>
                  <span className="transaction-icon">
                    <AppIcon name="history" size={17} />
                  </span>
                  <span className="data-row-main">
                    <strong>{order.product_name}</strong>
                    <small>
                      {order.order_type === "buy" ? "模拟申购" : "模拟赎回"}
                    </small>
                  </span>
                  <strong>{money(order.amount_minor, order.currency)}</strong>
                </div>
              ))}
            </div>
          ) : (
            <p className="page-empty">暂无理财操作记录。</p>
          )}
        </section>
      </div>

      <div className="page-alert">
        <AppIcon name="info" size={17} />
        产品收益为模拟参考，不构成投资建议。风险等级和最终执行结果均由服务端复核。
      </div>

      <RiskAssessmentForm />
    </div>
  );
}
