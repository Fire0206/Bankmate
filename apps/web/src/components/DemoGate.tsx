import {
  staticPreviewMode,
  type DemoSessionResponse,
} from "../api/client";
import { AppIcon } from "./AppIcon";

export function DemoGate({
  session,
  apiState,
  onEnter,
  onRetry,
}: {
  session: DemoSessionResponse | null;
  apiState: "checking" | "connected" | "unavailable";
  onEnter: () => void;
  onRetry: () => void;
}) {
  const displayName =
    session?.display_name === "Demo User One"
      ? "演示用户 One"
      : (session?.display_name ?? "正在读取演示身份");

  return (
    <main className="demo-gate">
      <section className="demo-gate-story">
        <div className="demo-brand">
          <span className="demo-brand-mark">F</span>
          <span>FinOrch</span>
        </div>
        <p className="demo-gate-kicker">Trusted banking agent</p>
        <h1>
          不只是回答问题，
          <br />
          而是把事情办完。
        </h1>
        <p className="demo-gate-lede">
          用一句自然语言管理账单、卡片、订阅、转账与模拟理财。每一个建议都能解释，
          每一项变更都需要确认，每一次执行都有审计。
        </p>
        <div className="demo-gate-capabilities">
          <span>
            <AppIcon name="shield" size={17} />
            服务端权限与确认
          </span>
          <span>
            <AppIcon name="clock" size={17} />
            持久任务与恢复
          </span>
          <span>
            <AppIcon name="history" size={17} />
            可回放的执行审计
          </span>
        </div>
        <p className="demo-gate-footnote">
          本产品使用合成银行数据，不连接真实账户、支付网络或征信服务。
        </p>
      </section>

      <section className="demo-access">
        <div className="demo-access-orbit demo-access-orbit-one" />
        <div className="demo-access-orbit demo-access-orbit-two" />
        <article className="demo-access-card">
          <header>
            <span className="demo-access-icon">
              <AppIcon name="assistant" size={21} />
            </span>
            <span
              className={
                "demo-service-state demo-service-" +
                (apiState === "connected"
                  ? "ready"
                  : apiState === "checking"
                    ? "checking"
                    : "offline")
              }
            >
              <i />
              {apiState === "connected"
                ? staticPreviewMode
                  ? "静态预览已就绪"
                  : "演示服务已就绪"
                : apiState === "checking"
                  ? "正在连接服务"
                  : "服务暂时不可用"}
            </span>
          </header>
          <div className="demo-identity">
            <span className="demo-avatar">{displayName.slice(0, 1)}</span>
            <span>
              <small>当前合成身份</small>
              <strong>{displayName}</strong>
            </span>
          </div>
          <dl>
            <div>
              <dt>数据环境</dt>
              <dd>
                {session?.environment === "development" ? "本地开发" : "测试"}
              </dd>
            </div>
            <div>
              <dt>数据集</dt>
              <dd>{session?.dataset_version ?? "读取中"}</dd>
            </div>
            <div>
              <dt>模型模式</dt>
              <dd>
                {session?.agent_provider === "fake" ? "确定性演示" : "兼容模型"}
              </dd>
            </div>
          </dl>
          <button
            className="demo-enter-button"
            disabled={apiState !== "connected" || !session}
            onClick={onEnter}
            type="button"
          >
            {apiState === "connected" && session
              ? staticPreviewMode
                ? "进入交互预览"
                : "进入演示账户"
              : apiState === "checking"
                ? "正在准备演示"
                : "等待服务连接"}
            <AppIcon name="arrow-right" size={18} />
          </button>
          {apiState === "unavailable" ? (
            <button
              className="demo-retry-button"
              onClick={onRetry}
              type="button"
            >
              重新连接
            </button>
          ) : null}
          <p>
            {staticPreviewMode
              ? "这是只读静态预览；所有页面可浏览，资金类操作需连接本地 API 后体验。"
              : "这是产品演示入口，不是真实用户登录。正式认证与远程部署尚未实现。"}
          </p>
        </article>
      </section>
    </main>
  );
}
