import { AppIcon, type IconName } from "./AppIcon";

export function PageHeader({
  eyebrow,
  title,
  description,
  actionLabel,
  actionIcon = "assistant",
  onAction,
  busy = false,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actionLabel?: string;
  actionIcon?: IconName;
  onAction?: () => void;
  busy?: boolean;
}) {
  return (
    <header className="page-heading">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actionLabel && onAction ? (
        <button
          className="page-heading-action"
          disabled={busy}
          onClick={onAction}
          type="button"
        >
          <AppIcon name={actionIcon} size={17} />
          {actionLabel}
        </button>
      ) : null}
    </header>
  );
}
