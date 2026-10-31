import type { components } from "../generated/api";
import { AppIcon } from "./AppIcon";
import { cardLabel } from "./cardFormat";

type Card = components["schemas"]["CardResponse"];

export function CardList({
  cards,
  loading,
  refreshing,
  onRefresh,
  onManage,
  manageDisabled,
}: {
  cards: Card[];
  loading: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onManage: (card: Card) => void;
  manageDisabled: boolean;
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
          <p>当前账户</p>
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
                  (card.status !== "active" ? " card-icon-frozen" : "")
                }
              >
                <AppIcon name="cards" size={19} />
              </span>
              <span className="card-copy">
                <span className="card-name">{cardLabel(card.label)}</span>
                <span className="card-suffix">尾号 {card.card_suffix}</span>
              </span>
              <span className="card-row-end">
                <span
                  className={
                    "status-label " +
                    (card.status === "active"
                      ? "status-label-active"
                      : "status-label-frozen")
                  }
                >
                  <span aria-hidden="true" className="status-dot" />
                  {card.status === "active"
                    ? "正常"
                    : card.status === "lost"
                      ? "已挂失"
                      : card.status === "replaced"
                        ? "已补卡停用"
                        : "已冻结"}
                </span>
                {card.status === "lost" || card.status === "replaced" ? (
                  <span className="card-suffix">
                    {card.status === "lost" ? "不可解冻" : "旧卡已停用"}
                  </span>
                ) : (
                  <button
                    className="card-manage-button"
                    disabled={manageDisabled}
                    onClick={() => onManage(card)}
                    type="button"
                  >
                    {card.status === "active" ? "冻结" : "解冻"}
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
