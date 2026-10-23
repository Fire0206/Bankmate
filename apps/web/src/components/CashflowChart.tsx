import { useId, useMemo } from "react";

import type { BillSummaryResponse } from "../api/client";

type Trend = BillSummaryResponse["trends"][number];
type Point = { x: number; y: number };

function yuan(valueMinor: number): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 0,
  }).format(valueMinor / 100);
}

function monthLabel(month: string): string {
  const [, value] = month.split("-").map(Number);
  return `${value}月`;
}

function smoothPath(points: Point[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  return points.slice(1).reduce((path, point, index) => {
    const previous = points[index];
    const control = (previous.x + point.x) / 2;
    return `${path} C ${control} ${previous.y}, ${control} ${point.y}, ${point.x} ${point.y}`;
  }, `M ${points[0].x} ${points[0].y}`);
}

export function CashflowChart({
  trends,
  incomeMinor,
  expenseMinor,
  height = 196,
}: {
  trends: Trend[];
  incomeMinor: number;
  expenseMinor: number;
  height?: number;
}) {
  const gradientId = useId().replaceAll(":", "");
  const chart = useMemo(() => {
    const width = 1000;
    const top = 20;
    const bottom = height - 24;
    const values = trends.flatMap((item) => [
      item.income_minor / 100,
      item.expense_minor / 100,
    ]);
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const range = Math.max(max - min, 1);
    const point = (value: number, index: number): Point => ({
      x: trends.length <= 1 ? width / 2 : (index / (trends.length - 1)) * width,
      y: bottom - ((value - min) / range) * (bottom - top),
    });
    const incomePoints = trends.map((item, index) =>
      point(item.income_minor / 100, index),
    );
    const expensePoints = trends.map((item, index) =>
      point(item.expense_minor / 100, index),
    );
    const incomePath = smoothPath(incomePoints);
    const expensePath = smoothPath(expensePoints);
    const areaPath =
      incomePoints.length > 0
        ? `${incomePath} L ${incomePoints.at(-1)!.x} ${bottom} L ${incomePoints[0].x} ${bottom} Z`
        : "";
    return {
      width,
      top,
      bottom,
      incomePoints,
      expensePoints,
      incomePath,
      expensePath,
      areaPath,
    };
  }, [height, trends]);

  const label =
    trends.length > 0
      ? `近六个月现金流趋势，收入${yuan(incomeMinor)}，支出${yuan(expenseMinor)}。`
      : "暂无可展示的现金流趋势。";

  if (trends.length === 0) {
    return <div className="cashflow-chart is-empty">{label}</div>;
  }

  return (
    <div
      aria-label={label}
      className="cashflow-chart"
      role="img"
      style={{ height }}
    >
      <svg
        aria-hidden="true"
        className="cashflow-chart-svg"
        preserveAspectRatio="none"
        viewBox={`0 0 ${chart.width} ${height}`}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#8ead97" stopOpacity="0.22" />
            <stop offset="1" stopColor="#8ead97" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[25, 92, 159, 226].map((y) => (
          <line
            key={y}
            stroke="#d8ddd5"
            strokeDasharray="2 7"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
            x1="0"
            x2={chart.width}
            y1={y}
            y2={y}
          />
        ))}
        <path d={chart.areaPath} fill={`url(#${gradientId})`} />
        <path
          d={chart.expensePath}
          fill="none"
          stroke="#be9a58"
          strokeDasharray="6 6"
          strokeWidth="1.7"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={chart.incomePath}
          fill="none"
          stroke="#3e725d"
          strokeLinecap="round"
          strokeWidth="2.3"
          vectorEffect="non-scaling-stroke"
        />
        {chart.incomePoints.length ? (
          <circle
            cx={chart.incomePoints.at(-1)!.x}
            cy={chart.incomePoints.at(-1)!.y}
            fill="#f3f1e9"
            r="5"
            stroke="#3e725d"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
      </svg>
      <div className="cashflow-chart-labels">
        {trends.map((item) => (
          <span key={item.month}>{monthLabel(item.month)}</span>
        ))}
      </div>
    </div>
  );
}
