import { useState } from "react";

import type { CardListResponse } from "../api/client";
import { brand } from "../brand";
import { AppIcon } from "../components/AppIcon";
import { PageHeader } from "../components/PageHeader";
import { SkeletonRows } from "../components/Skeleton";
import { cardLabel } from "../components/cardFormat";
import { customerText } from "../userFacing";

type CardItem = CardListResponse["items"][number];

function yuan(minor: number | null | undefined): string {
  if (typeof minor !== "number" || !Number.isFinite(minor)) return "—";
  return `¥${(minor / 100).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
  })}`;
}

function statusLabel(status: CardItem["status"]): string {
  return {
    active: "正常",
    frozen: "已冻结",
    lost: "已挂失",
    replaced: "已停用",
  }[status];
}

function CardFace({ card }: { card: CardItem }) {
  const inactive = card.status !== "active";
  return (
    <article
      className={
        "card-face card-face-main" + (inactive ? " card-face-inactive" : "")
      }
    >
      <div className="card-face-top">
        <span className="card-face-brand">
          <span aria-hidden="true" className="card-face-mark">
            {brand.mark}
          </span>
          {brand.name}
        </span>
        <span className="card-face-type">借记卡</span>
      </div>
      <div className="card-face-middle">
        <span aria-hidden="true" className="card-face-chip">
          <i />
          <i />
          <i />
        </span>
        <span className="card-face-contactless" aria-hidden="true">
          )))
        </span>
      </div>
      <p className="card-face-number">
        <span>••••</span>
        <span>••••</span>
        <span>••••</span>
        <strong>{card.card_suffix}</strong>
      </p>
      <div className="card-face-bottom">
        <span>
          <small>账户持有人</small>
          <strong>个人账户</strong>
        </span>
        <span>
          <small>状态</small>
          <strong>{statusLabel(card.status)}</strong>
        </span>
      </div>
    </article>
  );
}

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
  onManage: (card: CardItem) => void;
  onPrompt: (prompt: string) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selectedCard =
    cards.find((card) => card.id === selectedId) ??
    cards.find((card) => card.status === "active") ??
    cards[0] ??
    null;
  const toggleLabel =
    selectedCard?.status === "active"
      ? "冻结此卡"
      : selectedCard?.status === "frozen"
        ? "解冻此卡"
        : selectedCard?.status === "lost"
          ? "申请补卡"
          : "申请新卡";

  function runPrimaryAction(card: CardItem) {
    if (card.status === "lost") {
      onPrompt(`为尾号 ${card.card_suffix} 的已挂失银行卡申请补卡`);
      return;
    }
    if (card.status === "replaced") {
      onPrompt("为我的日常账户申请一张新的借记卡");
      return;
    }
    onManage(card);
  }

  return (
    <div className="page-stack cards-page">
      <PageHeader
        actionIcon="cards"
        actionLabel="申请卡片"
        busy={busy}
        onAction={() => onPrompt("为我的日常账户申请一张借记卡")}
        title="银行卡"
      />

      {loading ? (
        <section className="card-workspace card-workspace-loading">
          <SkeletonRows count={4} />
        </section>
      ) : selectedCard ? (
        <section className="card-workspace">
          <header className="card-workspace-header">
            <h2>{customerText(cardLabel(selectedCard.label))}</h2>
          </header>

          <div className="card-workspace-grid">
            <div className="card-face-stage">
              <CardFace card={selectedCard} />
            </div>

            <aside className="card-control-panel">
              <header>
                <div>
                  <h3>卡片控制</h3>
                </div>
              </header>

              <dl className="card-control-facts">
                <div>
                  <dt>线上支付</dt>
                  <dd
                    className={
                      selectedCard.online_enabled ? "is-enabled" : "is-disabled"
                    }
                  >
                    {selectedCard.online_enabled ? "已开启" : "已关闭"}
                  </dd>
                </div>
                <div>
                  <dt>单笔限额</dt>
                  <dd>{yuan(selectedCard.single_limit_minor)}</dd>
                </div>
                <div>
                  <dt>每日限额</dt>
                  <dd>{yuan(selectedCard.daily_limit_minor)}</dd>
                </div>
                <div>
                  <dt>卡片尾号</dt>
                  <dd>•••• {selectedCard.card_suffix}</dd>
                </div>
              </dl>

              <div className="card-control-actions">
                <button
                  className="card-primary-action"
                  disabled={busy}
                  onClick={() => runPrimaryAction(selectedCard)}
                  type="button"
                >
                  {toggleLabel}
                </button>
                {selectedCard.status === "active" ||
                selectedCard.status === "frozen" ? (
                  <>
                    <button
                      disabled={busy}
                      onClick={() =>
                        onPrompt(
                          `${selectedCard.online_enabled ? "关闭" : "开启"}尾号 ${selectedCard.card_suffix} 的线上支付`,
                        )
                      }
                      type="button"
                    >
                      {selectedCard.online_enabled
                        ? "关闭线上支付"
                        : "开启线上支付"}
                    </button>
                    <button
                      className="card-danger-action"
                      disabled={busy}
                      onClick={() =>
                        onPrompt(
                          `挂失尾号 ${selectedCard.card_suffix} 的银行卡`,
                        )
                      }
                      type="button"
                    >
                      挂失此卡
                    </button>
                  </>
                ) : null}
              </div>
            </aside>
          </div>

          <section className="card-inventory">
            <header>
              <h2>全部卡片</h2>
              <div className="card-inventory-tools">
                <button
                  aria-label="同步银行卡状态"
                  className="card-sync-action"
                  disabled={refreshing}
                  onClick={onRefresh}
                  title="同步银行卡状态"
                  type="button"
                >
                  <AppIcon
                    className={refreshing ? "icon-spinning" : ""}
                    name="refresh"
                    size={15}
                  />
                </button>
                <button
                  disabled={busy}
                  onClick={() => onPrompt("查询我的银行卡申请状态")}
                  type="button"
                >
                  申请进度
                  <AppIcon name="arrow-right" size={14} />
                </button>
              </div>
            </header>

            <div className="card-inventory-list">
              {cards.map((card) => {
                const selected = card.id === selectedCard?.id;
                return (
                  <button
                    aria-pressed={selected}
                    className={
                      "card-inventory-item" + (selected ? " is-selected" : "")
                    }
                    key={card.id}
                    onClick={() => setSelectedId(card.id)}
                    type="button"
                  >
                    <span className="card-inventory-mark">
                      {customerText(cardLabel(card.label)).slice(0, 1)}
                    </span>
                    <span className="card-inventory-main">
                      <strong>{customerText(cardLabel(card.label))}</strong>
                      <small>
                        尾号 {card.card_suffix} ·{" "}
                        {card.online_enabled ? "线上支付" : "线上关闭"} ·{" "}
                        {statusLabel(card.status)}
                      </small>
                    </span>
                    <AppIcon name="arrow-right" size={15} />
                  </button>
                );
              })}
            </div>
          </section>
        </section>
      ) : (
        <section className="card-workspace">
          <p className="page-empty">当前账户没有银行卡。</p>
        </section>
      )}
    </div>
  );
}
