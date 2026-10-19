import { AppIcon } from "./AppIcon";

type Section = "assistant" | "cards";

const shortcuts = [
  ["overview", "账户余额", "查询我的账户余额"],
  ["bill", "账单", "我这个月花了多少钱"],
  ["subscriptions", "自动扣费", "我有哪些自动扣费"],
  ["transfer", "转账记录", "查看我的转账记录"],
  ["transfer", "AA 分账", "查看我的 AA 分账"],
  ["wealth", "理财", "查看适合我的理财产品"],
] as const;

export function Navigation({
  mobileOpen,
  activeSection,
  hasTask,
  onClose,
  onSelect,
  onShowDetails,
  onPrompt,
}: {
  mobileOpen: boolean;
  activeSection: Section;
  hasTask: boolean;
  onClose: () => void;
  onSelect: (section: Section) => void;
  onShowDetails: () => void;
  onPrompt: (prompt: string) => void;
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

          <p className="nav-section-label nav-section-spaced">业务查询</p>
          {shortcuts.map(([icon, label, prompt]) => (
            <button
              className="nav-link"
              key={label}
              onClick={() => {
                onPrompt(prompt);
                onClose();
              }}
              type="button"
            >
              <AppIcon name={icon} />
              <span>{label}</span>
            </button>
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
