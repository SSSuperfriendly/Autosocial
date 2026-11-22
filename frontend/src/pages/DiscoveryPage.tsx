import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";
import type { DiscoveryResult, Preferences, SystemStatus, TargetSchoolRow } from "../types";
import { backendLabel, discoveryStageLabel, fitLabelText, fitTone } from "../utils/labels";
import { asText, linesToText, textToLines } from "../utils/text";

type Props = {
  preferences: Preferences | null;
  systemStatus: SystemStatus | null;
  targetRows: TargetSchoolRow[];
  onDiscoveryFinished: () => void | Promise<void>;
};

type ProgressEvent = Record<string, unknown>;

const BACKENDS = ["bigmodel-search", "hybrid", "directory", "ddg", "openai-search"] as const;

function getBackendStatus(systemStatus: SystemStatus | null, backend: string) {
  if (!systemStatus) {
    return { configured: false, enabled: false, hint: "等待系统状态" };
  }
  if (backend === "bigmodel-search") {
    return {
      configured: systemStatus.bigmodel_search.configured,
      enabled: systemStatus.bigmodel_search.enabled_by_preference,
      hint: systemStatus.bigmodel_search.model,
    };
  }
  if (backend === "openai-search") {
    return {
      configured: systemStatus.openai_search.configured,
      enabled: systemStatus.openai_search.enabled_by_preference,
      hint: systemStatus.openai_search.model,
    };
  }
  if (backend === "directory") {
    return {
      configured: systemStatus.directory_crawl.configured,
      enabled: systemStatus.directory_crawl.enabled_by_preference,
      hint: "官网目录与师资页跟链",
    };
  }
  if (backend === "ddg") {
    return {
      configured: systemStatus.ddg.configured,
      enabled: systemStatus.ddg.enabled_by_preference,
      hint: systemStatus.ddg.model,
    };
  }
  return {
    configured: true,
    enabled:
      systemStatus.directory_crawl.enabled_by_preference ||
      systemStatus.bigmodel_search.enabled_by_preference ||
      systemStatus.openai_search.enabled_by_preference ||
      systemStatus.ddg.enabled_by_preference,
    hint: "自动择优",
  };
}

export function DiscoveryPage({ preferences, systemStatus, targetRows, onDiscoveryFinished }: Props) {
  const schoolOptions = useMemo(
    () => Array.from(new Set(targetRows.map((item) => item.school).filter(Boolean))),
    [targetRows]
  );
  const [localPreferences, setLocalPreferences] = useState<Preferences | null>(preferences);
  const [schools, setSchools] = useState<string[]>(schoolOptions.slice(0, 6));
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DiscoveryResult | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [progress, setProgress] = useState(0);
  const [displayProgress, setDisplayProgress] = useState(0);
  const timerRef = useRef<number | null>(null);
  const animationRef = useRef<number | null>(null);

  useEffect(() => {
    setLocalPreferences(preferences);
  }, [preferences]);

  useEffect(() => {
    setSchools((current) => (current.length ? current : schoolOptions.slice(0, 6)));
  }, [schoolOptions]);

  useEffect(() => {
    if (!loading) {
      setDisplayProgress(progress);
      return;
    }
    if (animationRef.current) window.clearInterval(animationRef.current);
    animationRef.current = window.setInterval(() => {
      setDisplayProgress((current) => {
        if (current < progress) return Math.min(progress, current + 0.03);
        return Math.min(0.96, current + 0.004);
      });
    }, 180);
    return () => {
      if (animationRef.current) window.clearInterval(animationRef.current);
    };
  }, [loading, progress]);

  useEffect(() => {
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      if (animationRef.current) window.clearInterval(animationRef.current);
    };
  }, []);

  const preferredTopics = useMemo(
    () => linesToText(localPreferences?.research.preferred_topics ?? []),
    [localPreferences]
  );
  const acceptableTopics = useMemo(
    () => linesToText(localPreferences?.research.acceptable_topics ?? []),
    [localPreferences]
  );
  const excludedTopics = useMemo(
    () => linesToText(localPreferences?.research.excluded_topics ?? []),
    [localPreferences]
  );
  const preferencesDirty = useMemo(
    () => JSON.stringify(localPreferences) !== JSON.stringify(preferences),
    [localPreferences, preferences]
  );
  const selectedBackendStatus = getBackendStatus(systemStatus, localPreferences?.discovery.preferred_backend ?? "hybrid");
  const backendAllowed = (backend: string) => {
    const discovery = localPreferences?.discovery;
    if (!discovery) return false;
    const values: Record<string, boolean> = { "bigmodel-search": discovery.allow_bigmodel_search, "openai-search": discovery.allow_openai_search, directory: discovery.allow_directory_crawl, ddg: discovery.allow_ddg, hybrid: discovery.allow_hybrid };
    return values[backend] ?? false;
  };
  const selectedBackendAllowed = backendAllowed(localPreferences?.discovery.preferred_backend || "hybrid");
  const schoolPreview = useMemo(() => {
    if (!schools.length) return "未选择学校";
    if (schools.length <= 4) return schools.join(" / ");
    return `${schools.slice(0, 4).join(" / ")} 等 ${schools.length} 所`;
  }, [schools]);
  const preferredPreview = useMemo(() => {
    const items = localPreferences?.research.preferred_topics.filter(Boolean) ?? [];
    if (items.length) {
      return `${items.slice(0, 2).join(" / ")}${items.length > 2 ? ` 等 ${items.length} 项` : ""}`;
    }
    return localPreferences?.research.primary_focus || "未填写";
  }, [localPreferences]);

  const latestEvent = events[events.length - 1];
  const latestDetails = (latestEvent?.details as Record<string, unknown> | undefined) ?? {};
  const latestCurrent = Number(latestEvent?.current ?? 0);
  const latestTotal = Number(latestEvent?.total ?? 0);
  const currentStage = String(latestEvent?.stage ?? (loading ? "prepare" : "done"));
  const stageSteps = [
    { key: "prepare", label: "准备" },
    { key: "search", label: "检索" },
    { key: "dedupe", label: "去重" },
    { key: "extract", label: "抽取" },
    { key: "done", label: "完成" },
  ];
  const currentStepIndex = stageSteps.findIndex((item) => item.key === currentStage);

  async function persistPreferences(showMessage = true) {
    if (!localPreferences) return;
    await api.savePreferences(localPreferences);
    if (showMessage) {
      setMessage("研究偏好已保存，后续导师发现会按这套画像来跑。");
    }
  }

  async function handleSavePreferences() {
    setError("");
    setMessage("");
    try {
      await persistPreferences(true);
      await onDiscoveryFinished();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存研究偏好失败。");
    }
  }

  async function handleRun() {
    if (!localPreferences) return;
    setLoading(true);
    setError("");
    setMessage("");
    setEvents([]);
    setProgress(0.03);
    setDisplayProgress(0.08);
    setResult(null);

    try {
      if (preferencesDirty) {
        await persistPreferences(false);
      }

      const task = await api.createDiscoveryTask({
        backend: localPreferences.discovery.preferred_backend,
        schools,
        limit_per_school: localPreferences.discovery.limit_per_school,
        max_crawl_pages: localPreferences.discovery.max_crawl_pages,
        max_crawl_depth: localPreferences.discovery.max_crawl_depth,
      });

      timerRef.current = window.setInterval(async () => {
        try {
          const snapshot = await api.getDiscoveryTask(task.task_id);
          setEvents(snapshot.events);
          setProgress(snapshot.progress);

          if (snapshot.status === "completed" && snapshot.result) {
            setResult(snapshot.result);
            setProgress(1);
            setDisplayProgress(1);
            setMessage("发现任务已完成，结果已同步到导师池。");
            await onDiscoveryFinished();
            setLoading(false);
            if (timerRef.current) window.clearInterval(timerRef.current);
          }

          if (snapshot.status === "failed") {
            setError(snapshot.error ?? "发现任务失败，请检查后端日志。");
            setLoading(false);
            if (timerRef.current) window.clearInterval(timerRef.current);
          }
        } catch (pollError) {
          setError(pollError instanceof Error ? pollError.message : "轮询任务状态失败。");
          setLoading(false);
          if (timerRef.current) window.clearInterval(timerRef.current);
        }
      }, 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法启动检索任务。");
      setLoading(false);
    }
  }

  if (!localPreferences) {
    return <div className="page-stack">正在加载发现页...</div>;
  }

  return (
    <div className="page-stack page-stack-tight">
      <SectionCard
        title="发现导师"
        actions={
          <div className="inline-actions">
            <button className="ghost-button" onClick={handleSavePreferences} disabled={!preferencesDirty || loading} type="button">
              保存偏好
            </button>
            <button className="primary-button" onClick={handleRun} disabled={loading || schools.length === 0 || !selectedBackendStatus.configured || !selectedBackendAllowed} type="button">
              {loading ? "检索中..." : "开始发现"}
            </button>
          </div>
        }
      >
        <div className="chip-row">
          <span className={preferencesDirty ? "smart-chip warning" : "smart-chip muted"}>
            {preferencesDirty ? "研究偏好未保存" : "研究偏好已同步"}
          </span>
          <span className="smart-chip tertiary">学校 {schools.length}</span>
          <span className="smart-chip tertiary">后端 {backendLabel(localPreferences.discovery.preferred_backend)}</span>
          <span className="smart-chip tertiary">每校 {localPreferences.discovery.limit_per_school}</span>
        </div>
        {message ? <div className="success-box">{message}</div> : null}
        {error ? <div className="error-box">{error}</div> : null}
        {!schoolOptions.length ? <p className="discovery-availability">先到“设置 → 目标学校”添加学校，再开始检索。也可以在“工作台”直接手动添加导师。</p> : null}
        {!selectedBackendStatus.configured ? <p className="discovery-availability">当前检索方式尚未配置。请配置对应搜索服务，或选择官网目录抓取。手动添加导师不受影响。</p> : !selectedBackendAllowed ? <p className="discovery-availability">当前检索方式已关闭，请在下方开启并保存偏好。</p> : null}

        <div className="discovery-summary-strip">
          <div className="summary-tile">
            <span>当前后端</span>
            <strong>{backendLabel(localPreferences.discovery.preferred_backend)}</strong>
            <small>{selectedBackendStatus.configured ? "已接通" : "未配置"}</small>
          </div>
          <div className="summary-tile">
            <span>目标学校</span>
            <strong>{schools.length} 所</strong>
            <small>{schoolPreview}</small>
          </div>
          <div className="summary-tile">
            <span>研究偏好</span>
            <strong>{localPreferences.research.primary_focus || "未填写主方向"}</strong>
            <small>{preferredPreview}</small>
          </div>
        </div>

        <div className="discovery-panel-grid">
          <article className="settings-editor-card">
            <div className="settings-editor-head">
              <strong>研究偏好</strong>
            </div>
            <div className="form-grid form-grid-simple">
              <label>
                主方向
                <input
                  value={localPreferences.research.primary_focus}
                  onChange={(event) =>
                    setLocalPreferences({
                      ...localPreferences,
                      research: { ...localPreferences.research, primary_focus: event.target.value },
                    })
                  }
                />
              </label>
              <label>
                最低匹配分
                <input
                  type="number"
                  value={localPreferences.discovery.min_match_score}
                  onChange={(event) =>
                    setLocalPreferences({
                      ...localPreferences,
                      discovery: { ...localPreferences.discovery, min_match_score: Number(event.target.value) || 0 },
                    })
                  }
                />
              </label>
            </div>

            <div className="split-grid split-grid-simple">
              <label>
                重点偏好
                <textarea
                  value={preferredTopics}
                  onChange={(event) =>
                    setLocalPreferences({
                      ...localPreferences,
                      research: { ...localPreferences.research, preferred_topics: textToLines(event.target.value) },
                    })
                  }
                  placeholder="每行一个方向"
                />
              </label>
              <label>
                可接受方向
                <textarea
                  value={acceptableTopics}
                  onChange={(event) =>
                    setLocalPreferences({
                      ...localPreferences,
                      research: { ...localPreferences.research, acceptable_topics: textToLines(event.target.value) },
                    })
                  }
                  placeholder="每行一个方向"
                />
              </label>
            </div>

            <div className="split-grid split-grid-simple">
              <label>
                明确排除
                <textarea
                  value={excludedTopics}
                  onChange={(event) =>
                    setLocalPreferences({
                      ...localPreferences,
                      research: { ...localPreferences.research, excluded_topics: textToLines(event.target.value) },
                    })
                  }
                  placeholder="每行一个方向"
                />
              </label>
              <label>
                补充说明
                <textarea
                  value={localPreferences.research.free_text_notes}
                  onChange={(event) =>
                    setLocalPreferences({
                      ...localPreferences,
                      research: { ...localPreferences.research, free_text_notes: event.target.value },
                    })
                  }
                  placeholder="补充研究偏好、可接受范围和排除条件"
                />
              </label>
            </div>
          </article>

          <article className="settings-editor-card">
            <div className="settings-editor-head">
              <strong>发现配置</strong>
            </div>
            <div className="discovery-control-grid">
              <label>
                每校上限
                <input
                  type="number"
                  min={1}
                  value={localPreferences.discovery.limit_per_school}
                  onChange={(event) =>
                    setLocalPreferences({
                      ...localPreferences,
                      discovery: { ...localPreferences.discovery, limit_per_school: Number(event.target.value) || 1 },
                    })
                  }
                />
              </label>
              <label>
                抓取页数
                <input
                  type="number"
                  min={1}
                  value={localPreferences.discovery.max_crawl_pages}
                  onChange={(event) =>
                    setLocalPreferences({
                      ...localPreferences,
                      discovery: { ...localPreferences.discovery, max_crawl_pages: Number(event.target.value) || 1 },
                    })
                  }
                />
              </label>
              <label>
                跟链深度
                <input
                  type="number"
                  min={1}
                  value={localPreferences.discovery.max_crawl_depth}
                  onChange={(event) =>
                    setLocalPreferences({
                      ...localPreferences,
                      discovery: { ...localPreferences.discovery, max_crawl_depth: Number(event.target.value) || 1 },
                    })
                  }
                />
              </label>
            </div>

            <div className="settings-editor-head">
              <strong>搜索后端</strong>
            </div>
            <div className="backend-picker">
              {BACKENDS.map((item) => {
                const status = getBackendStatus(systemStatus, item);
                const statusText = !status.configured ? "未配置" : backendAllowed(item) ? "可用" : "已关闭";
                return (
                  <button
                    key={item}
                    type="button"
                    className={localPreferences.discovery.preferred_backend === item ? "backend-pill active" : "backend-pill"}
                    onClick={() =>
                      setLocalPreferences({
                        ...localPreferences,
                        discovery: { ...localPreferences.discovery, preferred_backend: item },
                      })
                    }
                  >
                    <span>{backendLabel(item)}</span>
                    <small>{status.hint}</small>
                    <em className={status.configured ? "backend-state online" : "backend-state offline"}>{statusText}</em>
                  </button>
                );
              })}
            </div>

            <div className="settings-editor-head"><strong>启用的检索方式</strong></div>
            <div className="chip-row">
              {([['allow_bigmodel_search', '智谱'], ['allow_openai_search', 'OpenAI'], ['allow_directory_crawl', '官网目录'], ['allow_ddg', 'DuckDuckGo'], ['allow_hybrid', '混合']] as const).map(([key, label]) => <label className="mentor-checkbox-label" key={key}><input type="checkbox" checked={localPreferences.discovery[key]} onChange={(event) => setLocalPreferences({ ...localPreferences, discovery: { ...localPreferences.discovery, [key]: event.target.checked } })} />{label}</label>)}
            </div>

            <div className="settings-editor-head">
              <strong>目标学校</strong>
            </div>
            <div className="school-picker">
              {schoolOptions.map((school) => {
                const checked = schools.includes(school);
                return (
                  <button
                    type="button"
                    key={school}
                    className={checked ? "school-pill active" : "school-pill"}
                    onClick={() =>
                      setSchools((current) => (checked ? current.filter((item) => item !== school) : [...current, school]))
                    }
                  >
                    <span>{school}</span>
                    <small>{checked ? "已选" : "加入"}</small>
                  </button>
                );
              })}
            </div>
            <div className="subtle-note">低匹配候选也会先进导师池，只打“低匹配”标签，不会黑盒消失。</div>
          </article>
        </div>
      </SectionCard>

      {(loading || events.length > 0) && (
        <SectionCard title="进度">
          <div className="discovery-progress-panel discovery-progress-panel-clean">
            <div className="progress-stage-grid">
              {stageSteps.map((step, index) => {
                const state =
                  currentStepIndex === -1
                    ? "upcoming"
                    : index < currentStepIndex
                      ? "done"
                      : index === currentStepIndex
                        ? "active"
                        : "upcoming";
                return (
                  <div className={`progress-stage-card ${state}`} key={step.key}>
                    <span>{step.label}</span>
                  </div>
                );
              })}
            </div>

            <div className="progress-summary">
              <div className="progress-title-wrap">
                <strong>{discoveryStageLabel(String(latestEvent?.stage ?? "prepare"))}</strong>
                <span>{asText(latestEvent?.message, "任务已启动，等待进度返回。")}</span>
              </div>
              <strong>{Math.round(displayProgress * 100)}%</strong>
            </div>

            <div className="live-progress-bar animated">
              <div className="live-progress-fill" style={{ width: `${Math.max(6, Math.round(displayProgress * 100))}%` }} />
            </div>

            <div className="discovery-inline-stats">
              <div className="fit-chip">
                <span>进度</span>
                <strong>{latestTotal ? `${latestCurrent}/${latestTotal}` : "准备中"}</strong>
              </div>
              <div className="fit-chip">
                <span>入池</span>
                <strong>{asText(latestDetails.ingested, "0")}</strong>
              </div>
              <div className="fit-chip">
                <span>复核</span>
                <strong>{asText(latestDetails.review_required, "0")}</strong>
              </div>
              <div className="fit-chip">
                <span>未入池</span>
                <strong>{asText(latestDetails.not_ingested, "0")}</strong>
              </div>
            </div>

            <div className="event-timeline">
              {events.slice(-6).map((event, index) => (
                <div className="timeline-item" key={index}>
                  <span className="timeline-stage">{discoveryStageLabel(asText(event.stage))}</span>
                  <p>{asText(event.message)}</p>
                </div>
              ))}
            </div>
          </div>
        </SectionCard>
      )}

      {result ? (
        <>
          <SectionCard title="结果">
            <div className="discovery-inline-stats">
              <div className="fit-chip">
                <span>发现</span>
                <strong>{result.discovered_count}</strong>
              </div>
              <div className="fit-chip">
                <span>入池</span>
                <strong>{result.ingested_count}</strong>
              </div>
              <div className="fit-chip">
                <span>待复核</span>
                <strong>{result.review_required_rows.length}</strong>
              </div>
              <div className="fit-chip">
                <span>未入池</span>
                <strong>{result.not_ingested_rows.length}</strong>
              </div>
            </div>
          </SectionCard>

          <SectionCard title="待复核">
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>学校</th>
                    <th>学院</th>
                    <th>姓名</th>
                    <th>邮箱</th>
                    <th>标签</th>
                    <th>原因</th>
                  </tr>
                </thead>
                <tbody>
                  {result.review_required_rows.length ? (
                    result.review_required_rows.slice(0, 20).map((row, index) => (
                      <tr key={`${row.url}-${index}`}>
                        <td>{asText(row.school, "-")}</td>
                        <td>{asText(row.institute, "-")}</td>
                        <td>{asText(row.name, "-")}</td>
                        <td>{asText(row.email, "-")}</td>
                        <td>
                          <StatusBadge text={fitLabelText(asText(row.fit_label))} tone={fitTone(asText(row.fit_label))} />
                        </td>
                        <td>{asText(row.review_reason || row.fit_reason, "-")}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={6}>这一轮没有待复核候选。</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <SectionCard title="未入池原因">
            {result.not_ingested_rows.length === 0 ? (
              <div className="success-box">这一轮没有真正失败的候选。低匹配候选也会先进池并打标签。</div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>学校</th>
                      <th>学院</th>
                      <th>标题</th>
                      <th>链接</th>
                      <th>原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.not_ingested_rows.slice(0, 20).map((row, index) => (
                      <tr key={`${row.url}-${index}`}>
                        <td>{asText(row.school, "-")}</td>
                        <td>{asText(row.institute, "-")}</td>
                        <td>{asText(row.title, "-")}</td>
                        <td>{asText(row.url, "-")}</td>
                        <td>{asText(row.reason, "-")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>
        </>
      ) : null}
    </div>
  );
}
