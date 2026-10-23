import type { ReactNode } from "react";

export type IconName =
  | "assistant"
  | "cards"
  | "overview"
  | "bill"
  | "transfer"
  | "subscriptions"
  | "wealth"
  | "history"
  | "menu"
  | "close"
  | "refresh"
  | "send"
  | "arrow-right"
  | "clock"
  | "chevron-down"
  | "info"
  | "check"
  | "shield";

const drawings: Record<IconName, ReactNode> = {
  assistant: (
    <>
      <path d="M20 11.5a7.5 7.5 0 0 1-8 7.5 8.9 8.9 0 0 1-3.5-.7L4 20l1.2-3.5A7.2 7.2 0 0 1 4 12c0-4.4 3.6-8 8-8s8 3.1 8 7.5Z" />
      <path d="M8 11h8M8 14h5" />
    </>
  ),
  cards: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 10h18M7 15h3" />
    </>
  ),
  overview: (
    <>
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
      <rect x="13" y="3" width="8" height="5" rx="1.5" />
      <rect x="13" y="10" width="8" height="11" rx="1.5" />
      <rect x="3" y="13" width="8" height="8" rx="1.5" />
    </>
  ),
  bill: (
    <>
      <path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z" />
      <path d="M9 8h6M9 12h6M9 16h3" />
    </>
  ),
  transfer: (
    <>
      <path d="M4 7h15l-4-4M19 7l-4 4" />
      <path d="M20 17H5l4 4M5 17l4-4" />
    </>
  ),
  subscriptions: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M5.7 9A7 7 0 0 1 18 6l2 1M4 17l2 1a7 7 0 0 0 12.3-3" />
    </>
  ),
  wealth: (
    <>
      <path d="M3 3v18h18" />
      <path d="m7 14 4-4 3 3 6-7" />
    </>
  ),
  history: (
    <>
      <path d="M3 12a9 9 0 1 0 2.6-6.4L3 8" />
      <path d="M3 3v5h5M12 7v5l3 2" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  refresh: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M5.6 9a7 7 0 0 1 11.6-2L20 12M4 12l2.8 5a7 7 0 0 0 11.6-2" />
    </>
  ),
  send: <path d="m5 12 7-7 7 7M12 5v14" />,
  "arrow-right": <path d="M5 12h14m-6-6 6 6-6 6" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  "chevron-down": <path d="m6 9 6 6 6-6" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  shield: (
    <>
      <path d="M12 3 5 6v5c0 4.5 2.8 8 7 10 4.2-2 7-5.5 7-10V6l-7-3Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
};

export function AppIcon({
  name,
  size = 18,
  className,
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      height={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      viewBox="0 0 24 24"
      width={size}
    >
      {drawings[name]}
    </svg>
  );
}
