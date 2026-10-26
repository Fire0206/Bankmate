import { pages, type PageKey } from "../pageConfig";
import { brand } from "../brand";

const navigationLabels: Record<PageKey, string> = {
  overview: "账户总览",
  assistant: "助手",
  bills: "账单",
  cards: "银行卡",
  transfers: "转账",
  subscriptions: "自动扣费",
  investments: "理财",
};

export function Navigation({
  activePage,
  displayName,
  mobileOpen,
  onClose,
  onNavigate,
}: {
  activePage: PageKey;
  displayName: string;
  mobileOpen: boolean;
  onClose: () => void;
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
          aria-label={`${brand.name} 首页`}
          className="brand-block"
          href="#/overview"
          onClick={(event) => {
            event.preventDefault();
            onNavigate("overview");
            onClose();
          }}
        >
          <span aria-hidden="true" className="brand-symbol">
            {brand.mark}
          </span>
          <span className="brand-copy">
            <strong className="brand-name">{brand.name}</strong>
          </span>
        </a>

        <nav aria-label="工作区导航" className="nav-list">
          {pages.map((page) => (
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
            </a>
          ))}
        </nav>

        <div className="sidebar-profile">
          <span className="sidebar-profile-avatar">
            {displayName.slice(0, 1)}
          </span>
          <span className="sidebar-profile-copy">
            <strong>{displayName}</strong>
            <small>个人账户</small>
          </span>
        </div>
      </aside>
    </>
  );
}
