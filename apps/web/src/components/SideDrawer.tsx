import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { AppIcon } from "./AppIcon";

export function SideDrawer({
  title,
  subtitle,
  children,
  onClose,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawerRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [onClose]);

  return createPortal(
    <div
      className="drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        aria-label={title}
        aria-modal="true"
        className="side-drawer"
        ref={drawerRef}
        role="dialog"
        tabIndex={-1}
      >
        <header className="side-drawer-header">
          <div>
            <p>{subtitle}</p>
            <h2>{title}</h2>
          </div>
          <button
            aria-label={"关闭" + title}
            className="modal-close modal-close-inline"
            onClick={onClose}
            ref={closeRef}
            type="button"
          >
            <AppIcon name="close" size={18} />
          </button>
        </header>
        <div className="side-drawer-content">{children}</div>
      </aside>
    </div>,
    document.body,
  );
}
