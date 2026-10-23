import { useEffect } from "react";
import { createPortal } from "react-dom";

import { AppIcon } from "./AppIcon";

export type ToastMessage = {
  id: string;
  title: string;
  message: string;
  tone: "success" | "warning" | "error";
};

export function Toast({
  toast,
  onDismiss,
}: {
  toast: ToastMessage;
  onDismiss: () => void;
}) {
  useEffect(() => {
    const timer = window.setTimeout(onDismiss, 4500);
    return () => window.clearTimeout(timer);
  }, [onDismiss, toast.id]);

  return createPortal(
    <div
      aria-live="polite"
      className={"toast toast-" + toast.tone}
      role="status"
    >
      <span className="toast-icon">
        <AppIcon name={toast.tone === "success" ? "check" : "info"} size={17} />
      </span>
      <span>
        <strong>{toast.title}</strong>
        <small>{toast.message}</small>
      </span>
      <button aria-label="关闭提示" onClick={onDismiss} type="button">
        <AppIcon name="close" size={15} />
      </button>
    </div>,
    document.body,
  );
}
