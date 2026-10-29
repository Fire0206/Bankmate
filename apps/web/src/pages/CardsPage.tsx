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
    active: "正常使用",
    frozen: "已冻结",
    lost: "已挂失",
    replaced: "已停用",
  }[status];
}

function CardFace({
  card,
  holderName,
}: {
  card: CardItem;
  holderName: string;
}) {
  const inactive = card.status !== "active";
  return (
    <article
      aria-label={`${customerText(cardLabel(card.label))}，尾号 ${card.card_suffix}，${statusLabel(card.status)}`}
      className={"card-face" + (inactive ? " card-face-inactive" : "")}
    >
      <header className="card-face-top">
        <span className="card-face-brand">
          <span aria-hidden="true" className="card-face-mark">
            {brand.mark}
          </span>
          <strong>{brand.name}</strong>
        </span>
        <span className="card-face-kind">借记卡</span>
      </header>

      <div className="card-face-chip-row">
        <svg
          aria-hidden="true"
          className="card-face-chip"
          fill="none"
          viewBox="0 0 44 34"
        >
          <rect height="32" rx="6" width="42" x="1" y="1" />
          <path d="M15 1v32M29 1v32M1 12h42M1 23h42M15 12v11M29 12v11" />
        </svg>
        <svg
          aria-hidden="true"
          className="card-face-contactless"
          fill="none"
          viewBox="0 0 24 24"
        >
          <path d="M7.5 8a6 6 0 0 0 0 8M11 5a10 10 0 0 0 0 14M14.5 2.5a13.5 13.5 0 0 0 0 19" />
        </svg>
      </div>

      <p
        className="card-face-number"
        aria-label={`卡号尾号 ${card.card_suffix}`}
      >
        <span aria-hidden="true">••••</span>
        <span aria-hidden="true">••••</span>
        <span aria-hidden="true">••••</span>
        <strong>{card.card_suffix}</strong>
      </p>

      <footer className="card-face-bottom">
        <span>
          <small>持卡人</small>
          <strong>{holderName}</strong>
        </span>
        <span className={`card-face-state card-state-${card.status}`}>
          <i aria-hidden="true">{card.status === "active" ? "✓" : "Ⅱ"}</i>
          <strong>{statusLabel(card.status)}</strong>
        </span>
      </footer>
    </article>
  );
}

export function CardsPage({
  cards,
  loading,
  refreshing,
  busy,
  holderName,
  onRefresh,
  onManage,
  onPrompt,
}: {
  cards: CardListResponse["items"];
  loading: boolean;
  refreshing: boolean;
  busy: boolean;
  holderName: string;
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
  const otherCards = cards.filter((card) => card.id !== selectedCard?.id);
  const canManageCardControls =
    selectedCard?.status === "active" || selectedCard?.status === "frozen";

  const primaryAction =
    selectedCard?.status === "active"
      ? "冻结银行卡"
      : selectedCard?.status === "frozen"
        ? "解冻银行卡"
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
        actionLabel="申请银行卡"
        busy={busy}
        onAction={() => onPrompt("为我的日常账户申请一张借记卡")}
        title="银行卡"
      />

      {loading ? (
        <section className="card-workspace card-workspace-loading">
          <SkeletonRows count={4} />
        </section>
      ) : selectedCard ? (
        <section aria-label="银行卡详情" className="card-workspace">
          <div className="card-spotlight">
            <div className="card-face-stage">
              <CardFace card={selectedCard} holderName={holderName} />
            </div>

            <section
              aria-labelledby="card-control-title"
              className="card-control-panel"
            >
              <header className="card-control-heading">
                <div>
                  <h2 id="card-control-title">
                    {customerText(cardLabel(selectedCard.label))}
                  </h2>
                </div>
              </header>

              <button
                className="card-primary-action"
                disabled={busy}
                onClick={() => runPrimaryAction(selectedCard)}
                type="button"
              >
                {primaryAction}
                <AppIcon name="arrow-right" size={17} />
              </button>

              {canManageCardControls ? (
                <div className="card-settings-list">
                  <button
                    className="card-setting-row"
                    disabled={busy}
                    onClick={() =>
                      onPrompt(
                        `调整尾号 ${selectedCard.card_suffix} 的银行卡交易限额`,
                      )
                    }
                    type="button"
                  >
                    <span>
                      <strong>交易限额</strong>
                      <small>
                        单笔 {yuan(selectedCard.single_limit_minor)} · 每日{" "}
                        {yuan(selectedCard.daily_limit_minor)}
                      </small>
                    </span>
                    <span className="card-setting-action">调整</span>
                    <AppIcon name="arrow-right" size={16} />
                  </button>
                  <button
                    className="card-setting-row"
                    disabled={busy}
                    onClick={() =>
                      onPrompt(
                        `${selectedCard.online_enabled ? "关闭" : "开启"}尾号 ${selectedCard.card_suffix} 的线上支付`,
                      )
                    }
                    type="button"
                  >
                    <span>
                      <strong>线上支付</strong>
                      <small>
                        {selectedCard.online_enabled ? "已开启" : "已关闭"}
                      </small>
                    </span>
                    <span className="card-setting-action">
                      {selectedCard.online_enabled ? "关闭" : "开启"}
                    </span>
                    <AppIcon name="arrow-right" size={16} />
                  </button>
                </div>
              ) : null}

              {selectedCard.status === "active" ||
              selectedCard.status === "frozen" ? (
                <button
                  className="card-lost-action"
                  disabled={busy}
                  onClick={() =>
                    onPrompt(`挂失尾号 ${selectedCard.card_suffix} 的银行卡`)
                  }
                  type="button"
                >
                  挂失银行卡
                  <AppIcon name="arrow-right" size={15} />
                </button>
              ) : null}
            </section>
          </div>

          <section className="card-inventory">
            <header>
              <h2>其他银行卡</h2>
              <div className="card-inventory-tools">
                <button
                  aria-label="刷新银行卡"
                  className="card-sync-action"
                  disabled={refreshing}
                  onClick={onRefresh}
                  title="刷新银行卡"
                  type="button"
                >
                  <AppIcon
                    className={refreshing ? "icon-spinning" : ""}
                    name="refresh"
                    size={16}
                  />
                  <span>刷新</span>
                </button>
                <button
                  disabled={busy}
                  onClick={() => onPrompt("查询我的银行卡申请状态")}
                  type="button"
                >
                  申请进度
                  <AppIcon name="arrow-right" size={15} />
                </button>
              </div>
            </header>

            {otherCards.length ? (
              <div className="card-inventory-list">
                {otherCards.map((card) => (
                  <button
                    aria-label={`${customerText(cardLabel(card.label))}，尾号 ${card.card_suffix}，${statusLabel(card.status)}，切换银行卡`}
                    className="card-inventory-item"
                    key={card.id}
                    onClick={() => setSelectedId(card.id)}
                    type="button"
                  >
                    <span className="card-inventory-main">
                      <strong>{customerText(cardLabel(card.label))}</strong>
                      <small>
                        尾号 {card.card_suffix} <i aria-hidden="true">·</i>{" "}
                        {statusLabel(card.status)}
                      </small>
                    </span>
                    <AppIcon name="arrow-right" size={16} />
                  </button>
                ))}
              </div>
            ) : (
              <p className="card-inventory-empty">目前只有这一张银行卡。</p>
            )}
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
