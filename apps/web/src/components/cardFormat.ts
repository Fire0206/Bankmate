export function cardLabel(label: string): string {
  const localized: Record<string, string> = {
    "Everyday debit": "日常借记卡",
    "Savings debit": "储蓄借记卡",
    "Travel debit": "旅行借记卡",
  };
  return localized[label] ?? label;
}
