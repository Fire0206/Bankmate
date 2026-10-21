import { AppIcon } from "./AppIcon";

export type Section = "assistant" | "cards";

export function Navigation({
  mobileOpen,
  activeSection,
  onClose,
  onSelect,
}: {
  mobileOpen: boolean;
  activeSection: Section;
  onClose: () => void;
  onSelect: (section: Section) => void;
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
            aria-current={activeSection === "cards" ? "page" : undefined}
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
        </nav>
      </aside>
      <nav aria-label="手机端导航" className="mobile-tabs">
        <a
          aria-current={activeSection === "assistant" ? "page" : undefined}
          className={
            activeSection === "assistant"
              ? "mobile-tab mobile-tab-active"
              : "mobile-tab"
          }
          href="#assistant"
          onClick={() => {
            onSelect("assistant");
            onClose();
          }}
        >
          <AppIcon name="assistant" size={21} />
          <span>智能助手</span>
        </a>
        <a
          aria-current={activeSection === "cards" ? "page" : undefined}
          className={
            activeSection === "cards"
              ? "mobile-tab mobile-tab-active"
              : "mobile-tab"
          }
          href="#cards"
          onClick={() => {
            onSelect("cards");
            onClose();
          }}
        >
          <AppIcon name="cards" size={21} />
          <span>银行卡</span>
        </a>
      </nav>
    </>
  );
}
