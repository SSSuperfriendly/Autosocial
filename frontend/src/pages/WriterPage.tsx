import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import type { Draft, Professor } from "../types";
import {
  EMPTY_WRITER_FORM,
  formFromProfessor,
  isCleanProfessor,
  professorLabel,
  writerFormCompleteness,
  type WriterFormState,
} from "../utils/mentor";

type ThinkingMode = "conservative" | "proactive";

type Props = {
  professors: Professor[];
  selectedProfessorId?: number | null;
  selectedProfessorLoadKey?: number;
  resetKey?: number;
  onNewProfessor?: () => void;
  onGenerated: () => void | Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
};

export function WriterPage({
  professors,
  selectedProfessorId,
  selectedProfessorLoadKey = 0,
  resetKey = 0,
  onNewProfessor,
  onGenerated,
  onDirtyChange,
}: Props) {
  const [form, setForm] = useState<WriterFormState>(EMPTY_WRITER_FORM);
  const [thinkingMode, setThinkingMode] = useState<ThinkingMode>("conservative");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftDirty, setDraftDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loadingDraft, setLoadingDraft] = useState(false);
  const [draftLoadKey, setDraftLoadKey] = useState(0);
  const lastLoadedRequestRef = useRef(0);
  const lastResetKeyRef = useRef(resetKey);
  const operationInFlight = busy || saving || savingDraft;

  const recentProfessors = useMemo(() => [...professors].sort((a, b) => Date.parse(b.updated_at || b.created_at || "") - Date.parse(a.updated_at || a.created_at || "")).slice(0, 8), [professors]);
  const canGenerate = form.name.trim() && form.school.trim();
  const completeness = useMemo(() => writerFormCompleteness(form), [form]);
  const modeText = form.professor_id ? "编辑导师" : "新增导师";
  const draftStats = draft
    ? {
        bodyChars: draft.body.length,
        subjectChars: draft.subject.length,
      }
    : null;

  const savedProfessor = professors.find((item) => item.id === form.professor_id);
  const formDirty = JSON.stringify(form) !== JSON.stringify(savedProfessor ? formFromProfessor(savedProfessor) : EMPTY_WRITER_FORM);
  const dirty = formDirty || draftDirty;

  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    if (!form.professor_id) {
      setLoadingDraft(false);
      return;
    }
    let cancelled = false;
    setLoadingDraft(true);
    api.drafts().then((result) => {
      if (cancelled) return;
      const saved = result.rows.filter((item) => item.professor_id === form.professor_id).sort((a, b) => b.draft_id - a.draft_id)[0];
      setDraft(saved || null);
      setDraftDirty(false);
    }).catch((err) => {
      if (!cancelled) setError(err instanceof Error ? err.message : "加载已保存草稿失败。");
    }).finally(() => { if (!cancelled) setLoadingDraft(false); });
    return () => { cancelled = true; };
  }, [form.professor_id, draftLoadKey]);

  useEffect(() => {
    if (!selectedProfessorId) return;
    if (operationInFlight) return;
    if (lastLoadedRequestRef.current === selectedProfessorLoadKey) return;
    const professor = professors.find((item) => item.id === selectedProfessorId);
    if (!professor) return;
    if (dirty && !window.confirm("当前导师或草稿有未保存修改，确定重新载入导师吗？")) {
      lastLoadedRequestRef.current = selectedProfessorLoadKey;
      return;
    }
    setForm(formFromProfessor(professor));
    setDraft(null);
    setDraftDirty(false);
    setDraftLoadKey((key) => key + 1);
    setMessage("已载入导师信息。");
    setError("");
    lastLoadedRequestRef.current = selectedProfessorLoadKey;
  }, [professors, selectedProfessorId, selectedProfessorLoadKey, operationInFlight]);

  useEffect(() => {
    if (lastResetKeyRef.current === resetKey || operationInFlight) return;
    lastResetKeyRef.current = resetKey;
    if (dirty && !window.confirm("当前导师或草稿有未保存修改，确定新增导师吗？")) return;
    setForm(EMPTY_WRITER_FORM);
    setDraft(null);
    setDraftDirty(false);
    setMessage("");
    setError("");
    lastLoadedRequestRef.current = 0;
  }, [resetKey, operationInFlight]);

  function patch(patchValue: Partial<WriterFormState>) {
    setForm((current) => ({ ...current, ...patchValue }));
  }

  function handleNewProfessor() {
    if (operationInFlight) return;
    if (dirty && !window.confirm("当前导师或草稿有未保存修改，确定新增导师吗？")) return;
    onNewProfessor?.();
    setForm(EMPTY_WRITER_FORM);
    setDraft(null);
    setDraftDirty(false);
    setMessage("已开始新增老师。");
    setError("");
    lastLoadedRequestRef.current = 0;
  }

  async function handleSaveProfessor() {
    if (!canGenerate) {
      setError("请至少填写导师姓名和学校。");
      return;
    }

    setSaving(true);
    setMessage("");
    setError("");
    try {
      const result = await api.saveWriterProfessor({
        ...form,
        thinking_mode: thinkingMode,
      });
      setForm((current) => ({ ...current, professor_id: result.professor.id }));
      setMessage("导师已保存到导师池。");
      await onGenerated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存导师失败。");
    } finally {
      setSaving(false);
    }
  }

  async function handleGenerate() {
    if (!canGenerate) {
      setError("请至少填写导师姓名和学校。");
      return;
    }

    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await api.generateWriterDraft({
        ...form,
        thinking_mode: thinkingMode,
      });
      setForm((current) => ({ ...current, professor_id: result.professor.id }));
      setDraft(result.draft);
      setDraftDirty(false);
      setMessage("邮件草稿已生成。");
      await onGenerated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成草稿失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveDraft() {
    if (!draft) return;
    if (!draft.subject.trim() || !draft.body.trim()) {
      setError("请先填写邮件主题和正文。");
      return;
    }

    setSavingDraft(true);
    setMessage("");
    setError("");
    try {
      const result = await api.saveWriterDraft({
        draft_id: draft.draft_id,
        professor_id: draft.professor_id,
        subject: draft.subject,
        body: draft.body,
      });
      setDraft(result.draft);
      setDraftDirty(false);
      setMessage("邮件草稿已保存。");
      await onGenerated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存草稿失败。");
    } finally {
      setSavingDraft(false);
    }
  }

  async function writeClipboard(text: string) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
    } catch {
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "true");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    if (!copied) {
      throw new Error("浏览器拒绝复制，请手动选中文本复制。");
    }
  }

  async function copyText(text: string, label: string) {
    try {
      await writeClipboard(text);
      setMessage(`${label}已复制。`);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label}复制失败。`);
    }
  }

  async function copyFullEmail() {
    if (!draft) return;
    try {
      await writeClipboard(`主题：${draft.subject}\n\n${draft.body}`);
      setMessage("主题和正文已复制。");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "复制全部失败。");
    }
  }

  return (
    <div className="page-stack page-stack-tight writer-page">
      <SectionCard
        title="写信"
        actions={
          <div className="inline-actions">
            <button className="ghost-button" onClick={handleNewProfessor} disabled={operationInFlight} type="button">
              新增老师
            </button>
            <button className="ghost-button" onClick={handleSaveProfessor} disabled={operationInFlight || !canGenerate} type="button">
              {saving ? "保存中..." : "保存导师"}
            </button>
            <button className="primary-button" onClick={handleGenerate} disabled={operationInFlight || loadingDraft || !canGenerate} type="button">
              {busy ? "生成中..." : "生成邮件"}
            </button>
          </div>
        }
      >
        <div className="writer-status-row">
          <span>{modeText}</span>
          <span>必填 {completeness.requiredFilled}/{completeness.requiredTotal}</span>
          <span>完整度 {completeness.filled}/{completeness.total}</span>
          {form.professor_id ? <span>ID {form.professor_id}</span> : null}
        </div>

        <div className="completeness-panel">
          <div className="completeness-bar">
            <div style={{ width: `${completeness.percent}%` }} />
          </div>
          <div className="completeness-items">
            {completeness.items.map((item) => (
              <span className={item.filled ? "complete" : item.required ? "required" : ""} key={item.key}>
                {item.label}
              </span>
            ))}
          </div>
        </div>

        <div className="writer-mode-row">
          <button
            className={thinkingMode === "conservative" ? "writer-mode active" : "writer-mode"}
            onClick={() => setThinkingMode("conservative")}
            disabled={operationInFlight}
            type="button"
          >
            稳妥版
          </button>
          <button
            className={thinkingMode === "proactive" ? "writer-mode active" : "writer-mode"}
            onClick={() => setThinkingMode("proactive")}
            disabled={operationInFlight}
            type="button"
          >
            主动版
          </button>
        </div>

        {recentProfessors.length ? (
          <div className="recent-professor-strip">
            <span>最近导师</span>
            {recentProfessors.map((row) => (
              <button
                key={row.id}
                onClick={() => {
                  if (dirty && !window.confirm("当前导师或草稿有未保存修改，确定切换导师吗？")) return;
                  setForm(formFromProfessor(row));
                  setDraft(null);
                  setDraftDirty(false);
                  setDraftLoadKey((key) => key + 1);
                  setMessage("已载入导师信息。");
                  setError("");
                }}
                type="button"
                disabled={operationInFlight}
              >
                {professorLabel(row)}
              </button>
            ))}
          </div>
        ) : null}

        {message ? <div className="success-box">{message}</div> : null}
        {error ? <div className="error-box">{error}</div> : null}

        <fieldset className="writer-fields" disabled={operationInFlight}>
        <div className="writer-grid">
          <label>
            导师姓名
            <input value={form.name} onChange={(event) => patch({ name: event.target.value })} placeholder="请输入导师姓名" />
          </label>
          <label>
            邮箱
            <input value={form.email} onChange={(event) => patch({ email: event.target.value })} placeholder="可选" />
          </label>
          <label>
            学校
            <input value={form.school} onChange={(event) => patch({ school: event.target.value })} placeholder="请输入学校名称" />
          </label>
          <label>
            学院
            <input value={form.institute} onChange={(event) => patch({ institute: event.target.value })} placeholder="可选" />
          </label>
          <label>
            职称
            <input value={form.title} onChange={(event) => patch({ title: event.target.value })} placeholder="可选" />
          </label>
          <label>
            个人主页
            <input value={form.profile_url} onChange={(event) => patch({ profile_url: event.target.value })} placeholder="可选" />
          </label>
        </div>

        <div className="writer-text-grid">
          <label>
            导师方向
            <textarea
              value={form.research_summary}
              onChange={(event) => patch({ research_summary: event.target.value })}
              placeholder="填写导师主要研究领域与关键词"
            />
          </label>
          <label>
            导师简介 / 你看到的信息
            <textarea
              value={form.professor_intro}
              onChange={(event) => patch({ professor_intro: event.target.value })}
              placeholder="可以粘贴主页简介、研究经历、代表性项目，空着也可以。"
            />
          </label>
        </div>

        <label>
          给自己的备注
          <input value={form.notes} onChange={(event) => patch({ notes: event.target.value })} placeholder="可选，比如：优先联系、方向很匹配" />
        </label>
        </fieldset>
      </SectionCard>

      <SectionCard
        title="邮件草稿"
        actions={
          draft ? (
            <div className="inline-actions">
              {draftStats ? (
                <span className="draft-count-chip">
                  {draftDirty ? "未保存 · " : ""}{draftStats.subjectChars} / {draftStats.bodyChars} 字
                </span>
              ) : null}
              <button className="ghost-button" onClick={handleSaveDraft} disabled={operationInFlight} type="button">
                {savingDraft ? "保存中..." : "保存草稿"}
              </button>
              <button className="ghost-button" onClick={() => copyText(draft.subject, "主题")} type="button">
                复制主题
              </button>
              <button className="ghost-button" onClick={() => copyText(draft.body, "正文")} type="button">
                复制正文
              </button>
              <button className="primary-button" onClick={copyFullEmail} type="button">
                复制全部
              </button>
            </div>
          ) : null
        }
      >
        {!draft ? (
          <div className="empty-state">{loadingDraft ? "正在加载已保存的草稿…" : "填写导师信息后，点击“生成邮件”。生成后请核对事实，再复制到邮箱中发送。"}</div>
        ) : (
          <div className="writer-draft-card">
            <label>
              主题
              <input
                value={draft.subject}
                disabled={operationInFlight}
                onChange={(event) => {
                  setDraft({ ...draft, subject: event.target.value });
                  setDraftDirty(true);
                }}
              />
            </label>
            <label>
              正文
              <textarea
                className="draft-body writer-draft-body"
                value={draft.body}
                disabled={operationInFlight}
                onChange={(event) => {
                  setDraft({ ...draft, body: event.target.value });
                  setDraftDirty(true);
                }}
              />
            </label>
          </div>
        )}
      </SectionCard>
    </div>
  );
}
