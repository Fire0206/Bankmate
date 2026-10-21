import type { components } from "../generated/api";
import { AppIcon } from "./AppIcon";
import { cardLabel } from "./cardFormat";

type Card = components["schemas"]["CardResponse"];

export function CardList({
  cards,
  loading,
  refreshing,
  onRefresh,
  onAskAboutCard,
}: {
  cards: Card[];
  loading: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onAskAboutCard: (request: string) => void;
}) {
  return (
    <section
      aria-labelledby="cards-title"
      className="card-management-section"
      id="cards"
    >
      <div className="section-heading">
        <div>
          <h2 id="cards-title">我的银行卡</h2>
          <p>冻结或解冻前需要在智能助手中确认。</p>
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
              <button
                className="card-action-button"
                onClick={() =>
                  onAskAboutCard(
                    `${card.status === "active" ? "冻结" : "解冻"}尾号 ${card.card_suffix} 的卡`,
                  )
                }
                type="button"
              >
                {card.status === "active" ? "办理冻结" : "办理解冻"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
