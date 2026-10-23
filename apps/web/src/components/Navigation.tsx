import { pages, type PageKey } from "../pageConfig";

const navigationLabels: Record<PageKey, string> = {
  overview: "总览",
  assistant: "Agent 助理",
  bills: "账单",
  cards: "银行卡",
  transfers: "转账",
  subscriptions: "订阅",
  investments: "投资",
};

export function Navigation({
  activePage,
  displayName,
  mobileOpen,
  onClose,
  onExit,
  onNavigate,
}: {
  activePage: PageKey;
  displayName: string;
  mobileOpen: boolean;
  onClose: () => void;
  onExit: () => void;
  onNavigate: (page: PageKey) => void;
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
          href="#/overview"
          onClick={(event) => {
            event.preventDefault();
            onNavigate("overview");
            onClose();
          }}
        >
          <span aria-hidden="true" className="brand-symbol" />
          <span className="brand-copy">
            <strong className="brand-name">FinOrch</strong>
            <small>PRIVATE BANKING</small>
          </span>
        </a>

        <nav aria-label="工作区导航" className="nav-list">
          <p className="nav-section-label">WORKSPACE</p>
          {pages.map((page, index) => (
            <a
              aria-current={activePage === page.key ? "page" : undefined}
              className={
                "nav-link" + (activePage === page.key ? " nav-link-active" : "")
              }
              href={"#/" + page.key}
              key={page.key}
              onClick={(event) => {
                event.preventDefault();
                onNavigate(page.key);
                onClose();
              }}
            >
              <span>{navigationLabels[page.key]}</span>
              <small>{String(index + 1).padStart(2, "0")}</small>
            </a>
          ))}
        </nav>

        <button
          className="sidebar-profile"
          onClick={onExit}
          title="退出演示账户"
          type="button"
        >
          <span className="sidebar-profile-avatar">
            {displayName.slice(0, 1)}
          </span>
          <span className="sidebar-profile-copy">
            <strong>{displayName}</strong>
            <small>个人账户 · Demo</small>
          </span>
        </button>
      </aside>
    </>
  );
}
