import { AppIcon, type IconName } from "./AppIcon";

const merchantPatterns: Array<[RegExp, IconName]> = [
  [/云盘|云服务|网盘/, "cloud"],
  [/腾讯视频|视频|影视/, "play"],
  [/网易云音乐|音乐/, "music"],
  [/咖啡|茶饮/, "coffee"],
  [/网约车|出行|打车|交通/, "car"],
  [/工资|薪资|收入/, "wallet"],
  [/房租|住房/, "home"],
  [/数码|手机|电子/, "device"],
  [/日用|购物|超市/, "bag"],
];

const categoryIcons: Record<string, IconName> = {
  订阅: "subscriptions",
  餐饮: "coffee",
  交通: "car",
  收入: "wallet",
  住房: "home",
  数码: "device",
  购物: "bag",
};

function iconFor(merchant: string, category?: string): IconName {
  const match = merchantPatterns.find(([pattern]) => pattern.test(merchant));
  return match?.[1] ?? categoryIcons[category ?? ""] ?? "bill";
}

export function MerchantMark({
  merchant,
  category,
  className = "",
}: {
  merchant: string;
  category?: string;
  className?: string;
}) {
  return (
    <span aria-hidden="true" className={`merchant-mark ${className}`.trim()}>
      <AppIcon name={iconFor(merchant, category)} size={19} />
    </span>
  );
}
