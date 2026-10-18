import type { components } from "../generated/api";
import { AppIcon } from "./AppIcon";
import { cardLabel } from "./cardFormat";

type Card = components["schemas"]["CardResponse"];

export function CardList({
  cards,
  loading,
  refreshing,
  onRefresh,
}: {
  cards: Card[];
  loading: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <section
      aria-labelledby="cards-title"
      className="context-section"
      id="cards"
    >
      <div className="section-heading">
        <div>
          <h2 id="cards-title">银行卡</h2>
          <p>当前演示账户</p>
        </div>
        <button
          aria-label="刷新银行卡"
          className="quiet-button refresh-button"
          disabled={loading || refreshing}
          onClick={onRefresh}
          type="button"
        >
          <AppIcon
            className={refreshing ? "icon-spinning" : undefined}
            name="refresh"
          />
          <span>{refreshing ? "更新中" : "刷新"}</span>
        </button>
      </div>

      {loading ? (
        <p className="inline-empty" role="status">
          正在读取银行卡…
        </p>
      ) : cards.length === 0 ? (
        <p className="inline-empty">当前账户下没有银行卡。</p>
      ) : (
        <ul className="card-list">
          {cards.map((card) => (
            <li className="card-row" key={card.id}>
              <span
                aria-hidden="true"
                className={
                  "card-icon" +
                  (card.status === "frozen" ? " card-icon-frozen" : "")
                }
              >
                <AppIcon name="cards" size={19} />
              </span>
              <span className="card-copy">
                <span className="card-name">{cardLabel(card.label)}</span>
                <span className="card-suffix">尾号 {card.card_suffix}</span>
              </span>
              <span
                className={
                  "status-label " +
                  (card.status === "active"
                    ? "status-label-active"
                    : "status-label-frozen")
                }
              >
                <span aria-hidden="true" className="status-dot" />
                {card.status === "active" ? "正常" : "已冻结"}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="card-footnote">卡片状态以服务端数据为准。</p>
    </section>
  );
}
