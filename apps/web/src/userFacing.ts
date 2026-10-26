/** Convert internal fixture labels into natural customer-facing copy. */
const NAME_LABELS: Record<string, string> = {
  "Demo User One": "林知远",
  "Demo User Two": "王小川",
};

export function customerName(value: string | null | undefined): string {
  if (!value) return "当前账户";
  return NAME_LABELS[value] ?? value;
}

export function customerText(value: string | null | undefined): string {
  if (!value) return "";
  let text = value;
  for (const [internalName, publicName] of Object.entries(NAME_LABELS)) {
    text = text.replaceAll(internalName, publicName);
  }
  return text
    .replaceAll("Everyday account", "日常账户")
    .replaceAll("Savings account", "储蓄账户")
    .replaceAll("Everyday debit", "日常借记卡")
    .replaceAll("Savings debit", "储蓄借记卡")
    .replaceAll("Travel debit", "旅行借记卡")
    .replaceAll(
      "非住房单笔支出达到演示提示阈值 ¥1,000。",
      "单笔非住房支出达到 ¥1,000，请核对交易。",
    )
    .replaceAll(
      "同一账户同一商户在同一天出现多笔相同金额扣款；这是重复扣费提示，不代表欺诈。",
      "同一商户在同一天出现多笔相同金额扣款，请核对交易；这不是欺诈结论。",
    )
    .replaceAll("模拟数码流水", "数码消费")
    .replaceAll("模拟订阅流水", "订阅扣款")
    .replaceAll("模拟餐饮流水", "餐饮消费")
    .replaceAll("模拟购物流水", "购物消费")
    .replaceAll("模拟交通流水", "交通支出")
    .replaceAll("模拟住房流水", "住房支出")
    .replaceAll("模拟收入流水", "收入")
    .replaceAll(
      "模拟净值固定，收益率为演示估值。",
      "净值为固定参考值，收益率为估算值。",
    )
    .replaceAll("中低风险短债类模拟产品", "中低风险短债类产品")
    .replaceAll("较高波动的指数类模拟产品", "较高波动的指数类产品")
    .replaceAll(
      "仅用于合成数据演示。请本人如实作答；模型不能代答，测评不代表真实银行适当性评估。",
      "请本人如实作答。结果仅用于虚拟产品的风险匹配，不代表真实银行适当性评估。",
    )
    .replaceAll(
      "账单规则发现同一账户、商户和 UTC 日期存在重复记录。这只是核对提示，不代表已判定为欺诈。",
      "同一商户在同一天出现多笔金额相同的扣款，请核对账单；这不代表欺诈结论。",
    )
    .replace(
      /(\d{4}-\d{2}) 的合成流水显示支出高于收入；可先检查较大的支出类别，再决定是否调整计划。/,
      "$1 的账单显示支出高于收入，可查看支出较多的类别。",
    )
    .replaceAll("确定性规则提示", "账单规则提醒")
    .replaceAll("服务端确定性规则", "账单规则")
    .replaceAll("按确定性规则生成", "根据账单记录整理")
    .replaceAll(
      "所有提示均由服务端账单规则生成。",
      "提醒依据来自账单记录，供你核对。",
    )
    .replaceAll(
      "服务端账单规则命中的提示，不代表欺诈结论。",
      "根据账单规则提供的核对提醒，不代表欺诈结论。",
    )
    .replaceAll("合成数据", "虚拟数据")
    .replaceAll("合成信息", "虚拟信息")
    .replaceAll(
      "系统没有使用行为数据，不会据此判断订阅是否浪费。",
      "是否继续订阅，请结合自己的使用情况决定。",
    )
    .replaceAll("演示提示阈值", "提醒阈值")
    .replaceAll("模拟", "")
    .replaceAll("演示", "")
    .replaceAll("Fake Provider", "本地服务")
    .replaceAll("demo_otp", "本地验证");
}

export function accountLabel(value: string): string {
  const labels: Record<string, string> = {
    "Everyday account": "日常账户",
    "Savings account": "储蓄账户",
  };
  return labels[value] ?? customerText(value);
}

export function cardDisplayName(value: string): string {
  const labels: Record<string, string> = {
    "Everyday debit": "日常借记卡",
    "Savings debit": "储蓄借记卡",
    "Travel debit": "旅行借记卡",
  };
  return labels[value] ?? customerText(value);
}

export function transactionDescription(
  description: string,
  category: string,
  direction: "income" | "expense",
): string {
  const label = customerText(description);
  if (label === description && !description.includes("模拟")) return label;
  return `${category}${direction === "income" ? "收入" : "支出"}`;
}
