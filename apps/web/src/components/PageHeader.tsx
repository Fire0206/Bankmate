import { AppIcon } from "./AppIcon";

export function PageHeader({
  eyebrow,
  title,
  description,
  actionLabel,
  onAction,
  busy = false,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  busy?: boolean;
}) {
  return (
    <header className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actionLabel && onAction ? (
        <button
          className="page-heading-action"
          disabled={busy}
          onClick={onAction}
          type="button"
        >
          <AppIcon name="assistant" size={17} />
          {actionLabel}
        </button>
      ) : null}
    </header>
  );
}
