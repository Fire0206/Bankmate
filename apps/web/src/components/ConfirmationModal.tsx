import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import type { components } from "../generated/api";
import { AppIcon } from "./AppIcon";
import { ConfirmationCard } from "./ConfirmationCard";

type Confirmation = components["schemas"]["ConfirmationResponse"];

export function ConfirmationModal({
  confirmation,
  busy,
  onConfirm,
  onCancel,
  onClose,
}: {
  confirmation: Confirmation;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) {
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = [
        ...dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
      ];
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (document.activeElement === dialog) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [busy, onClose]);

  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        aria-labelledby="confirmation-title"
        aria-modal="true"
        className="modal-dialog confirmation-dialog"
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <button
          aria-label="关闭确认窗口"
          className="modal-close"
          disabled={busy}
          onClick={onClose}
          ref={closeRef}
          type="button"
        >
          <AppIcon name="close" size={18} />
        </button>
        <ConfirmationCard
          busy={busy}
          confirmation={confirmation}
          onCancel={onCancel}
          onConfirm={onConfirm}
        />
      </div>
    </div>,
    document.body,
  );
}
