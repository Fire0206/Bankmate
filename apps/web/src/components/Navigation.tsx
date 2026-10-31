import { brand } from "../brand";
import { pages, type PageKey } from "../pageConfig";
import { AppIcon } from "./AppIcon";

const navigationGroups: Array<{ label: string; keys: PageKey[] }> = [
  { label: "工作台", keys: ["overview", "assistant"] },
  { label: "账户与资金", keys: ["bills", "cards", "transfers"] },
  { label: "财务规划", keys: ["subscriptions", "investments"] },
];

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
            <img alt="" src={brand.logoMark} />
          </span>
          <span className="brand-copy">
            <strong className="brand-name">{brand.name}</strong>
            <small>{brand.descriptor}</small>
          </span>
        </a>

        <nav aria-label="工作区导航" className="nav-list">
          {navigationGroups.map((group) => (
            <section className="nav-group" key={group.label}>
              <p className="nav-section-label">{group.label}</p>
              {group.keys.map((key) => {
                const page = pages.find((item) => item.key === key);
                if (!page) return null;
                return (
                  <a
                    aria-current={activePage === key ? "page" : undefined}
                    className={
                      "nav-link" +
                      (activePage === key ? " nav-link-active" : "")
                    }
                    href={"#/" + key}
                    key={key}
                    onClick={(event) => {
                      event.preventDefault();
                      onNavigate(key);
                      onClose();
                    }}
                  >
                    <AppIcon name={page.icon} size={17} />
                    <span>{page.label}</span>
                  </a>
                );
              })}
            </section>
          ))}
        </nav>

        <div className="sidebar-profile">
          <span className="sidebar-profile-avatar">
            {displayName.slice(0, 1)}
          </span>
          <span className="sidebar-profile-copy">
            <strong>{displayName}</strong>
            <small>
              <i aria-hidden="true" />
              本地账户
            </small>
          </span>
        </div>
      </aside>
    </>
  );
}
