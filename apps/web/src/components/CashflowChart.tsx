import { useMemo } from "react";
import type { CSSProperties } from "react";

import type { BillSummaryResponse } from "../api/client";

type Trend = BillSummaryResponse["trends"][number];

function currencyAmount(valueMinor: number, currencyCode: string): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: currencyCode,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(valueMinor / 100);
}

function monthLabel(month: string, previousMonth?: string): string {
  const [year, monthNumber] = month.split("-").map(Number);
  const previousYear = previousMonth
    ? Number(previousMonth.split("-")[0])
    : year;
  const yearLabel = previousYear === year ? "" : `${String(year).slice(-2)}年`;
  return `${yearLabel}${monthNumber}月`;
}

export function CashflowChart({
  trends,
  currencyCode,
}: {
  trends: Trend[];
  currencyCode: string;
}) {
  const maxMinor = useMemo(
    () =>
      Math.max(
        1,
        ...trends.flatMap((item) => [item.income_minor, item.expense_minor]),
      ),
    [trends],
  );

  const label =
    trends.length > 0
      ? `月度收支趋势。深色柱表示收入，浅灰柱表示支出。${trends
          .map(
            (item) =>
              `${item.month}收入${currencyAmount(item.income_minor, currencyCode)}，支出${currencyAmount(item.expense_minor, currencyCode)}`,
          )
          .join("；")}。`
      : "暂无可展示的现金流趋势。";

  if (trends.length === 0) {
    return <div className="cashflow-chart is-empty">{label}</div>;
  }

  return (
    <div aria-label={label} className="cashflow-chart" role="img">
      <div
        aria-hidden="true"
        className="cashflow-chart-bars"
        style={{ "--chart-month-count": trends.length } as CSSProperties}
      >
        {trends.map((item, index) => {
          const incomeHeight = (item.income_minor / maxMinor) * 100;
          const expenseHeight = (item.expense_minor / maxMinor) * 100;
          return (
            <div className="cashflow-chart-month" key={item.month}>
              <div className="cashflow-bar-pair">
                <span
                  className={
                    "cashflow-bar cashflow-bar-income" +
                    (item.income_minor > 0 ? " has-value" : "")
                  }
                  style={
                    { "--bar-height": `${incomeHeight}%` } as CSSProperties
                  }
                  title={`收入 ${currencyAmount(item.income_minor, currencyCode)}`}
                />
                <span
                  className={
                    "cashflow-bar cashflow-bar-expense" +
                    (item.expense_minor > 0 ? " has-value" : "")
                  }
                  style={
                    { "--bar-height": `${expenseHeight}%` } as CSSProperties
                  }
                  title={`支出 ${currencyAmount(item.expense_minor, currencyCode)}`}
                />
              </div>
              <span className="cashflow-month-label" title={item.month}>
                {monthLabel(item.month, trends[index - 1]?.month)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
