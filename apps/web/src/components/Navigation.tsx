import { AppIcon } from "./AppIcon";

type Section = "assistant" | "cards";

const plannedItems = [
  ["overview", "账户总览"],
  ["bill", "账单分析"],
  ["transfer", "转账"],
  ["subscriptions", "订阅管理"],
  ["wealth", "理财"],
] as const;

export function Navigation({
  mobileOpen,
  activeSection,
  hasTask,
  onClose,
  onSelect,
  onShowDetails,
}: {
  mobileOpen: boolean;
  activeSection: Section;
  hasTask: boolean;
  onClose: () => void;
  onSelect: (section: Section) => void;
  onShowDetails: () => void;
}) {
  return (
    <>
      {mobileOpen ? (
        <button
          aria-label="关闭导航菜单"
          className="nav-backdrop"
          onClick={onClose}
          type="button"
        />
      ) : null}
      <aside
        aria-label="主导航"
        className={"sidebar" + (mobileOpen ? " sidebar-open" : "")}
        id="main-navigation"
      >
        <a
          aria-label="FinOrch 首页"
          className="brand-block"
          href="#assistant"
          onClick={() => {
            onSelect("assistant");
            onClose();
          }}
        >
          <span aria-hidden="true" className="brand-symbol">
            F
          </span>
          <span className="brand-name">FinOrch</span>
        </a>

        <nav aria-label="工作区导航" className="nav-list">
          <p className="nav-section-label">工作区</p>
          <a
            aria-current={activeSection === "assistant" ? "page" : undefined}
            className={
              "nav-link" +
              (activeSection === "assistant" ? " nav-link-active" : "")
            }
            href="#assistant"
            onClick={() => {
              onSelect("assistant");
              onClose();
            }}
          >
            <AppIcon name="assistant" />
            <span>智能助手</span>
          </a>
          <a
            aria-current={activeSection === "cards" ? "location" : undefined}
            className={
              "nav-link" + (activeSection === "cards" ? " nav-link-active" : "")
            }
            href="#cards"
            onClick={() => {
              onSelect("cards");
              onClose();
            }}
          >
            <AppIcon name="cards" />
            <span>银行卡</span>
          </a>
          <button
            className="nav-link"
            disabled={!hasTask}
            onClick={onShowDetails}
            type="button"
          >
            <AppIcon name="history" />
            <span>操作记录</span>
          </button>

          <p className="nav-section-label nav-section-spaced">更多服务</p>
          {plannedItems.map(([icon, label]) => (
            <div
              aria-disabled="true"
              className="nav-link nav-link-disabled"
              key={label}
            >
              <AppIcon name={icon} />
              <span>{label}</span>
              <small>规划中</small>
            </div>
          ))}
        </nav>

        <div className="sidebar-note">
          <span className="sidebar-note-dot" />
          <span>模拟数据环境</span>
        </div>
      </aside>
    </>
  );
}
