import type { CardListResponse } from "../api/client";
import { AppIcon } from "../components/AppIcon";
import { PageHeader } from "../components/PageHeader";
import { SkeletonRows } from "../components/Skeleton";
import { cardLabel } from "../components/cardFormat";

export function CardsPage({
  cards,
  loading,
  refreshing,
  busy,
  onRefresh,
  onManage,
  onPrompt,
}: {
  cards: CardListResponse["items"];
  loading: boolean;
  refreshing: boolean;
  busy: boolean;
  onRefresh: () => void;
  onManage: (card: CardListResponse["items"][number]) => void;
  onPrompt: (prompt: string) => void;
}) {
  const active = cards.filter((card) => card.status === "active").length;
  const frozen = cards.filter((card) => card.status === "frozen").length;

  return (
    <div className="page-stack">
      <PageHeader
        actionLabel="咨询卡片安全"
        busy={busy}
        description="查看卡片状态，并在服务端确认后冻结或解冻模拟银行卡。"
        eyebrow="Card controls"
        onAction={() =>
          onPrompt("帮我检查银行卡状态，并告诉我有哪些安全控制可以做")
        }
        title="银行卡"
      />

      <div className="card-page-summary">
        <div>
          <span>可用卡片</span>
          <strong>{active}</strong>
        </div>
        <div>
          <span>已冻结</span>
          <strong>{frozen}</strong>
        </div>
        <button disabled={refreshing} onClick={onRefresh} type="button">
          <AppIcon
            className={refreshing ? "icon-spinning" : ""}
            name="refresh"
            size={16}
          />
          {refreshing ? "更新中" : "刷新状态"}
        </button>
      </div>

      <div className="card-page-grid">
        {loading ? (
          <>
            <div
              aria-hidden="true"
              className="physical-card physical-card-skeleton"
            />
            <div
              aria-hidden="true"
              className="physical-card physical-card-skeleton"
            />
          </>
        ) : cards.length ? (
          cards.map((card) => (
            <article
              className={
                "physical-card" + (card.status === "frozen" ? " is-frozen" : "")
              }
              key={card.id}
            >
              <div className="physical-card-top">
                <span>FinOrch</span>
                <span>{card.status === "active" ? "ACTIVE" : "FROZEN"}</span>
              </div>
              <div className="physical-card-chip" />
              <div className="physical-card-number">
                <span>••••</span>
                <span>••••</span>
                <span>••••</span>
                <strong>{card.card_suffix}</strong>
              </div>
              <div className="physical-card-bottom">
                <span>
                  <small>模拟银行卡</small>
                  <strong>{cardLabel(card.label)}</strong>
                </span>
                <span>
                  <small>状态</small>
                  <strong>
                    {card.status === "active" ? "正常" : "已冻结"}
                  </strong>
                </span>
              </div>
            </article>
          ))
        ) : (
          <p className="page-empty">当前账户没有银行卡。</p>
        )}
      </div>

      <section className="card-management-card">
        <header>
          <div>
            <p className="eyebrow">Safe actions</p>
            <h2>卡片控制</h2>
          </div>
          <span>每次操作都需要服务端确认</span>
        </header>
        <div className="management-list">
          {loading ? (
            <SkeletonRows count={2} />
          ) : (
            cards.map((card) => (
              <div className="management-row" key={card.id}>
                <span className="management-icon">
                  <AppIcon name="cards" size={18} />
                </span>
                <span>
                  <strong>{cardLabel(card.label)}</strong>
                  <small>
                    尾号 {card.card_suffix} ·{" "}
                    {card.status === "active" ? "正常可用" : "支付已停用"}
                  </small>
                </span>
                <button
                  disabled={busy}
                  onClick={() => onManage(card)}
                  type="button"
                >
                  {card.status === "active" ? "冻结此卡" : "解冻此卡"}
                </button>
              </div>
            ))
          )}
        </div>
        <div className="page-alert">
          <AppIcon name="info" size={17} />
          FinOrch 不显示完整卡号或
          PIN。冻结后仍可随时解冻，但旧确认会因卡片版本变化而失效。
        </div>
      </section>
    </div>
  );
}
