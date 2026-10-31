import { useEffect, useRef, useState } from "react";

import { apiClient } from "../api/client";
import { customerText } from "../userFacing";
import type {
  RiskAssessmentRequest,
  RiskAssessmentResponse,
  RiskQuestionnaireResponse,
} from "../api/client";

type PendingSubmission = { body: RiskAssessmentRequest; key: string };

export function RiskAssessmentForm() {
  const [questionnaire, setQuestionnaire] =
    useState<RiskQuestionnaireResponse | null>(null);
  const [latest, setLatest] = useState<RiskAssessmentResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<PendingSubmission | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([
      apiClient.readRiskQuestionnaire(),
      apiClient.readLatestRiskAssessment(),
    ])
      .then(([form, result]) => {
        if (!active) return;
        setQuestionnaire(form);
        setLatest(result);
      })
      .catch(() => {
        if (active) setError("暂时无法加载风险测评，请稍后再试。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function submit() {
    if (!questionnaire || submitting) return;
    const {
      time_horizon,
      loss_tolerance,
      liquidity_capacity,
      investment_experience,
    } = answers;
    if (
      [
        time_horizon,
        loss_tolerance,
        liquidity_capacity,
        investment_experience,
      ].some((value) => !Number.isInteger(value))
    ) {
      setError("请回答全部四个问题。");
      return;
    }
    const body: RiskAssessmentRequest = {
      questionnaire_version: questionnaire.questionnaire_version,
      time_horizon,
      loss_tolerance,
      liquidity_capacity,
      investment_experience,
    };
    const serialized = JSON.stringify(body);
    if (
      !pending.current ||
      JSON.stringify(pending.current.body) !== serialized
    ) {
      pending.current = { body, key: crypto.randomUUID() };
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await apiClient.submitRiskAssessment(
        pending.current.body,
        pending.current.key,
      );
      setLatest(result);
      pending.current = null;
    } catch (cause) {
      setError(
        cause instanceof Error
          ? `${cause.message}。请先查询最新结果；重试会沿用同一请求标识。`
          : "提交状态未知，请先查询最新结果。",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function refresh() {
    try {
      setLatest(await apiClient.readLatestRiskAssessment());
      setError(null);
    } catch {
      setError("暂时无法查询测评结果，请检查连接。");
    }
  }

  if (loading) return <p role="status">正在加载风险测评…</p>;
  if (!questionnaire) return <p role="alert">{error}</p>;

  return (
    <section aria-label="风险测评" className="risk-assessment">
      <h4>风险承受能力测评</h4>
      <p>{customerText(questionnaire.notice)}</p>
      {latest ? (
        <p className="risk-assessment-current">
          当前测评：{latest.risk_label}（R{latest.risk_level}）·{" "}
          {new Date(latest.assessed_at).toLocaleDateString("zh-CN")}
        </p>
      ) : null}
      {questionnaire.questions.map((question) => (
        <fieldset key={question.key}>
          <legend>{question.title}</legend>
          <div className="risk-assessment-options">
            {question.options.map((option) => (
              <label key={option.value}>
                <input
                  checked={answers[question.key] === option.value}
                  disabled={submitting}
                  name={question.key}
                  onChange={() => {
                    setAnswers((current) => ({
                      ...current,
                      [question.key]: option.value,
                    }));
                    setError(null);
                  }}
                  type="radio"
                  value={option.value}
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      <p className="risk-assessment-notice">
        完成后会更新账户风险等级；申购前还会再次检查产品是否匹配。
      </p>
      {error ? <p role="alert">{error}</p> : null}
      <div className="risk-assessment-actions">
        <button
          disabled={submitting}
          onClick={() => void submit()}
          type="button"
        >
          {submitting ? "正在提交…" : latest ? "重新测评" : "提交测评"}
        </button>
        <button
          disabled={submitting}
          onClick={() => void refresh()}
          type="button"
        >
          查询最新结果
        </button>
      </div>
    </section>
  );
}
