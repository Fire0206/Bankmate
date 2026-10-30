import { AppIcon, type IconName } from "./AppIcon";

// Local wordmarks for the synthetic transaction set. These are not copied
// third-party logo assets; unknown merchants use their first two characters.
const merchantWordmarks: Array<[RegExp, string]> = [
  [/腾讯视频/, "腾讯"],
  [/网易云音乐/, "网易"],
  [/云盘|云服务|网盘/, "云盘"],
  [/星河数码/, "星河"],
  [/咖啡工坊/, "咖啡"],
  [/日用百货|邻里超市/, "日用"],
  [/小满面馆/, "小满"],
  [/深圳地铁/, "地铁"],
  [/网约车/, "出行"],
  [/海边食堂/, "食堂"],
  [/工资|薪资/, "工资"],
  [/房租|住房/, "房租"],
];

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

function wordmarkFor(merchant: string): string | null {
  if (!merchant.trim()) return null;
  const known = merchantWordmarks.find(([pattern]) => pattern.test(merchant));
  return known?.[1] ?? Array.from(merchant.trim()).slice(0, 2).join("");
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
  const wordmark = wordmarkFor(merchant);

  return (
    <span
      aria-hidden="true"
      className={`merchant-mark${wordmark ? " merchant-mark--wordmark" : ""} ${className}`.trim()}
    >
      {wordmark ? (
        <span className="merchant-wordmark">{wordmark}</span>
      ) : (
        <AppIcon name={iconFor(merchant, category)} size={19} />
      )}
    </span>
  );
}
