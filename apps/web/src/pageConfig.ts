import type { IconName } from "./components/AppIcon";

export type PageKey =
  | "overview"
  | "assistant"
  | "bills"
  | "cards"
  | "transfers"
  | "subscriptions"
  | "investments";

export type PageMeta = {
  key: PageKey;
  label: string;
  shortLabel: string;
  description: string;
  icon: IconName;
};

export const pages: PageMeta[] = [
  {
    key: "overview",
    label: "账户总览",
    shortLabel: "总览",
    description: "账户、现金流和待处理事项",
    icon: "overview",
  },
  {
    key: "assistant",
    label: "助手",
    shortLabel: "助手",
    description: "查询和办理常用业务",
    icon: "assistant",
  },
  {
    key: "bills",
    label: "账单",
    shortLabel: "账单",
    description: "收支统计、交易记录和消费提醒",
    icon: "bill",
  },
  {
    key: "cards",
    label: "银行卡",
    shortLabel: "卡片",
    description: "卡片状态与安全控制",
    icon: "cards",
  },
  {
    key: "transfers",
    label: "转账",
    shortLabel: "转账",
    description: "余额、收款人和资金记录",
    icon: "transfer",
  },
  {
    key: "subscriptions",
    label: "自动扣费",
    shortLabel: "扣费",
    description: "周期扣费与续费管理",
    icon: "subscriptions",
  },
  {
    key: "investments",
    label: "理财",
    shortLabel: "理财",
    description: "产品、风险测评和持仓",
    icon: "wealth",
  },
];

export function pageFromHash(): PageKey {
  const candidate = window.location.hash.replace(/^#\/?/, "");
  return pages.some((page) => page.key === candidate)
    ? (candidate as PageKey)
    : "overview";
}

export function pageMeta(key: PageKey): PageMeta {
  return pages.find((page) => page.key === key) ?? pages[0];
}
