import type { CardListResponse } from "../api/client";
import { brand } from "../brand";
import { AppIcon } from "../components/AppIcon";
import { PageHeader } from "../components/PageHeader";
import { SkeletonRows } from "../components/Skeleton";
import { cardLabel } from "../components/cardFormat";
import { customerText } from "../userFacing";

function yuan(minor: number): string {
  return `¥${(minor / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`;
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
        description="查看银行卡状态、消费限额与线上支付设置。变更前需确认。"
        eyebrow="银行卡"
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

      <div className="card-page-actions">
        <button
          disabled={busy}
          onClick={() => onPrompt("为我的日常账户申请一张借记卡")}
          type="button"
        >
          申请借记卡
        </button>
        <button
          disabled={busy}
          onClick={() => onPrompt("查询我的银行卡申请状态")}
          type="button"
        >
          查看申请进度
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
                "physical-card" + (card.status !== "active" ? " is-frozen" : "")
              }
              key={card.id}
            >
              <div className="physical-card-top">
                <span>{brand.name}</span>
                <span>
                  {card.status === "active"
                    ? "ACTIVE"
                    : card.status === "lost"
                      ? "LOST"
                      : card.status === "replaced"
                        ? "REPLACED"
                        : "FROZEN"}
                </span>
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
                  <small>借记卡</small>
                  <strong>{customerText(cardLabel(card.label))}</strong>
                </span>
                <span>
                  <small>状态</small>
                  <strong>
                    {card.status === "active"
                      ? "正常"
                      : card.status === "lost"
                        ? "已挂失"
                        : card.status === "replaced"
                          ? "已补卡停用"
                          : "已冻结"}
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
            <p className="eyebrow">安全设置</p>
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
                  <strong>{customerText(cardLabel(card.label))}</strong>
                  <small>
                    尾号 {card.card_suffix} ·{" "}
                    {card.status === "active"
                      ? "正常可用"
                      : card.status === "lost"
                        ? "已挂失，不可解冻"
                        : card.status === "replaced"
                          ? "旧卡已停用"
                          : "支付已停用"}
                  </small>
                  <small>
                    单笔 {yuan(card.single_limit_minor)} · 每日{" "}
                    {yuan(card.daily_limit_minor)} · 线上消费
                    {card.online_enabled ? "已开启" : "已关闭"}
                  </small>
                </span>
                {card.status === "lost" ? (
                  <button
                    disabled={busy}
                    onClick={() =>
                      onPrompt(
                        `为尾号 ${card.card_suffix} 的已挂失银行卡申请补卡`,
                      )
                    }
                    type="button"
                  >
                    申请补卡
                  </button>
                ) : card.status !== "replaced" ? (
                  <div className="management-actions">
                    <button
                      disabled={busy}
                      onClick={() => onManage(card)}
                      type="button"
                    >
                      {card.status === "active" ? "冻结此卡" : "解冻此卡"}
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        onPrompt(`挂失尾号 ${card.card_suffix} 的银行卡`)
                      }
                      type="button"
                    >
                      挂失此卡
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        onPrompt(
                          `${card.online_enabled ? "关闭" : "开启"}尾号${card.card_suffix}的卡线上支付`,
                        )
                      }
                      type="button"
                    >
                      {card.online_enabled ? "关闭线上支付" : "开启线上支付"}
                    </button>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
        <div className="page-alert">
          <AppIcon name="info" size={17} />
          {brand.name} 不显示完整卡号或 PIN。挂失后无法解冻；补卡后旧卡停用。
        </div>
      </section>
    </div>
  );
}
