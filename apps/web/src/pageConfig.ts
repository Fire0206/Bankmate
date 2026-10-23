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
    label: "财务总览",
    shortLabel: "总览",
    description: "账户、现金流和待处理事项",
    icon: "overview",
  },
  {
    key: "assistant",
    label: "智能助手",
    shortLabel: "助手",
    description: "用自然语言完成银行任务",
    icon: "assistant",
  },
  {
    key: "bills",
    label: "账单分析",
    shortLabel: "账单",
    description: "消费分类、趋势和异常证据",
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
    label: "转账与分账",
    shortLabel: "转账",
    description: "余额、收款人和资金记录",
    icon: "transfer",
  },
  {
    key: "subscriptions",
    label: "订阅代扣",
    shortLabel: "扣费",
    description: "周期扣费与续费管理",
    icon: "subscriptions",
  },
  {
    key: "investments",
    label: "模拟理财",
    shortLabel: "理财",
    description: "产品、风险与模拟持仓",
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
