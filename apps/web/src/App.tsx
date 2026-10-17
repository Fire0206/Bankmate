import { useEffect, useState } from "react";

import type { paths } from "./generated/api";

type HealthResponse =
  paths["/api/v1/health"]["get"]["responses"][200]["content"]["application/json"];
type ApiState = "checking" | "connected" | "unavailable";
type HealthState = {
  refreshKey: number;
  state: ApiState;
  version: string | null;
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

const scenarios = [
  "智能转账",
  "账单分析",
  "理财操作",
  "卡片管理",
  "订阅与代扣管理",
  "跨场景联动",
];

async function readApiHealth(): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl}/api/v1/health`, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error(`API returned HTTP ${response.status}`);
  }

  return (await response.json()) as HealthResponse;
}

export default function App() {
  const [health, setHealth] = useState<HealthState>({
    refreshKey: 0,
    state: "checking",
    version: null,
  });
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;

    readApiHealth()
      .then((health) => {
        if (!active) return;
        setHealth({
          refreshKey,
          state: health.status === "ok" ? "connected" : "unavailable",
          version: health.version,
        });
      })
      .catch(() => {
        if (!active) return;
        setHealth({ refreshKey, state: "unavailable", version: null });
      });

    return () => {
      active = false;
    };
  }, [refreshKey]);

  const apiState = health.refreshKey === refreshKey ? health.state : "checking";
  const apiVersion = apiState === "connected" ? health.version : null;
  const statusLabel = {
    checking: "检查连接中",
    connected: "API 已连接",
    unavailable: "API 未连接",
  }[apiState];

  return (
    <main className="min-h-screen px-5 py-6 text-slate-950 sm:px-8 sm:py-9">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <a
            className="flex items-center gap-3"
            href="#home"
            aria-label="FinOrch 首页"
          >
            <span className="brand-mark" aria-hidden="true">
              F
            </span>
            <span>
              <span className="block text-lg font-semibold tracking-tight">
                FinOrch
              </span>
              <span className="block text-xs text-slate-500">
                AI Banking Agent
              </span>
            </span>
          </a>
          <div className="flex items-center gap-3">
            <span className="phase-pill">PHASE 0 · FOUNDATION</span>
            <a
              className="hidden text-sm font-medium text-slate-600 hover:text-slate-950 sm:block"
              href="http://127.0.0.1:8000/docs"
              target="_blank"
              rel="noreferrer"
            >
              API 文档 ↗
            </a>
          </div>
        </header>

        <section
          id="home"
          className="hero-panel mt-12 overflow-hidden rounded-[2rem] sm:mt-16"
        >
          <div className="hero-grid px-7 py-10 sm:px-12 sm:py-14 lg:px-16 lg:py-16">
            <div className="max-w-2xl">
              <p className="eyebrow">安全、可解释、由用户掌控</p>
              <h1 className="mt-5 text-4xl font-semibold leading-tight tracking-tight sm:text-5xl lg:text-6xl">
                让金融操作
                <br />
                <span className="text-emerald-700">清晰可控。</span>
              </h1>
              <p className="mt-6 max-w-xl text-base leading-7 text-slate-600 sm:text-lg">
                FinOrch 正在搭建一个面向模拟银行场景的 AI
                Agent。先把接口、安全边界和协作基础打牢，再逐步实现六大场景。
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <div className="status-chip" aria-live="polite">
                  <span
                    className={`status-dot status-${apiState}`}
                    aria-hidden="true"
                  />
                  <span>{statusLabel}</span>
                  {apiState === "connected" && apiVersion ? (
                    <span className="text-slate-400">v{apiVersion}</span>
                  ) : null}
                </div>
                <button
                  className="retry-button"
                  onClick={() => setRefreshKey((key) => key + 1)}
                  type="button"
                >
                  重新检查
                </button>
              </div>
            </div>
            <div className="hero-orbit hidden lg:block" aria-hidden="true">
              <div className="orbit-ring orbit-ring-outer" />
              <div className="orbit-ring orbit-ring-inner" />
              <div className="orbit-core">
                <span className="orbit-core-mark">F</span>
                <span className="orbit-core-label">FinOrch</span>
              </div>
              <span className="orbit-node orbit-node-one">Intent</span>
              <span className="orbit-node orbit-node-two">Confirm</span>
              <span className="orbit-node orbit-node-three">Execute</span>
            </div>
          </div>
          <div className="hero-foot flex flex-wrap items-center justify-between gap-3 px-7 py-4 text-sm sm:px-12 lg:px-16">
            <span>当前开发阶段：Phase 0 · Repository Foundation</span>
            <span className="text-slate-500">
              尚未连接真实银行、支付或 LLM 服务
            </span>
          </div>
        </section>

        <section className="mt-14 sm:mt-16" aria-labelledby="scenarios-heading">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="eyebrow">PRODUCT ROADMAP</p>
              <h2
                id="scenarios-heading"
                className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl"
              >
                六大场景，逐步构建
              </h2>
            </div>
            <span className="planned-pill">全部为规划中</span>
          </div>
          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {scenarios.map((scenario, index) => (
              <article className="scenario-card" key={scenario}>
                <span className="scenario-index">0{index + 1}</span>
                <h3 className="font-medium text-slate-800">{scenario}</h3>
                <span className="planned-label">PLANNED</span>
              </article>
            ))}
          </div>
        </section>

        <footer className="mt-16 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 py-6 text-xs text-slate-500">
          <span>FinOrch · 2026 深圳国际金融科技大赛 · 国内人工智能赛道</span>
          <span>演示与开发阶段仅使用模拟数据</span>
        </footer>
      </div>
    </main>
  );
}
