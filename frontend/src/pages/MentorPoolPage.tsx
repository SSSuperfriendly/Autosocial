import { useMemo, useState } from "react";

import { api } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";
import type { Professor } from "../types";
import {
  CONTACT_STAGE_OPTIONS,
  VERIFICATION_OPTIONS,
  contactStageLabel,
  contactStageTone,
  fitLabelText,
  fitTone,
  formatDateShort,
  verificationLabel,
  verificationTone,
} from "../utils/labels";
import { hasEnoughForWriting, isCleanProfessor, matchProfessor, professorCompleteness, professorUpdatedAt } from "../utils/mentor";

type Props = {
  professors: Professor[];
  onCreateProfessor: () => void;
  onUseProfessor: (professorId: number) => void;
  onChanged: () => void | Promise<void>;
};

type FilterKey = "all" | "ready" | "missing" | "draft" | "contacted" | "replied";
type SortKey = "priority" | "updated" | "school" | "completeness";

type MentorEditForm = {
  contact_stage: string;
  verification_status: string;
  shortlisted: boolean;
  matched_topics: string;
  notes: string;
};

const CONTACT_PRIORITY: Record<string, number> = {
  replied: 700,
  in_conversation: 680,
  sent_waiting: 620,
  ready_to_send: 560,
  draft_ready: 500,
  shortlisted: 430,
  reviewing: 360,
  new: 120,
  rejected: 20,
};

function topicList(row: Professor) {
  return String(row.matched_topics || "")
    .split("|")
    .map((item) => item.trim())
    .filter(Boolean);
}

function editFormFromProfessor(row: Professor): MentorEditForm {
  return {
    contact_stage: row.contact_stage || "new",
    verification_status: row.verification_status || "needs_review",
    shortlisted: Boolean(row.shortlisted),
    matched_topics: row.matched_topics || "",
    notes: row.notes || "",
  };
}

function progressPriority(row: Professor) {
  if (typeof row.interaction_priority_score === "number") {
    return row.interaction_priority_score;
  }
  const contactScore = CONTACT_PRIORITY[row.contact_stage] ?? 0;
  const replyBonus = row.last_replied_at ? 40 : 0;
  const contactedBonus = row.last_contacted_at ? 20 : 0;
  const shortlistBonus = row.shortlisted ? 10 : 0;
  return contactScore + replyBonus + contactedBonus + shortlistBonus;
}

export function MentorPoolPage({ professors, onCreateProfessor, onUseProfessor, onChanged }: Props) {
  const [searchTerm, setSearchTerm] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<MentorEditForm | null>(null);
  const [rescoring, setRescoring] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const normalizedSearch = searchTerm.trim().toLowerCase();

  const cleanRows = professors;
  const stats = useMemo(
    () => ({
      total: cleanRows.length,
      ready: cleanRows.filter(hasEnoughForWriting).length,
      draft: cleanRows.filter((row) => row.draft_status).length,
      missing: cleanRows.filter((row) => !hasEnoughForWriting(row)).length,
      contacted: cleanRows.filter((row) => ["sent_waiting", "replied", "in_conversation"].includes(row.contact_stage)).length,
      replied: cleanRows.filter((row) => ["replied", "in_conversation"].includes(row.contact_stage)).length,
    }),
    [cleanRows],
  );

  const rows = useMemo(
    () =>
      cleanRows
        .filter((row) => matchProfessor(row, normalizedSearch))
        .filter((row) => {
          if (filter === "ready") return hasEnoughForWriting(row);
          if (filter === "missing") return !hasEnoughForWriting(row);
          if (filter === "draft") return Boolean(row.draft_status);
          if (filter === "contacted") return ["sent_waiting", "replied", "in_conversation"].includes(row.contact_stage);
          if (filter === "replied") return ["replied", "in_conversation"].includes(row.contact_stage);
          return true;
        })
        .sort((a, b) => {
          if (sortKey === "school") {
            return `${a.school || ""}${a.name || ""}`.localeCompare(`${b.school || ""}${b.name || ""}`, "zh-CN");
          }
          if (sortKey === "completeness") {
            return professorCompleteness(b).filled - professorCompleteness(a).filled || progressPriority(b) - progressPriority(a);
          }
          if (sortKey === "updated") {
            return professorUpdatedAt(b) - professorUpdatedAt(a);
          }
          return (
            progressPriority(b) - progressPriority(a) ||
            (b.fit_score || 0) - (a.fit_score || 0) ||
            professorUpdatedAt(b) - professorUpdatedAt(a)
          );
        }),
    [cleanRows, filter, normalizedSearch, sortKey],
  );

  async function handleMoveToTrash(row: Professor) {
    const confirmed = window.confirm(`确认将 ${row.name || "这位导师"} 移入垃圾桶吗？`);
    if (!confirmed) return;

    setBusyId(row.id);
    setMessage("");
    setError("");
    try {
      await api.trashProfessors([row.id]);
      setMessage("导师已移入垃圾桶。");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "移入垃圾桶失败。");
    } finally {
      setBusyId(null);
    }
  }

  async function handleSaveEdit(row: Professor) {
    if (!editForm) return;
    setBusyId(row.id);
    setMessage("");
    setError("");
    try {
      await api.saveProfessors([
        {
          ...row,
          contact_stage: editForm.contact_stage,
          verification_status: editForm.verification_status,
          shortlisted: editForm.shortlisted,
          matched_topics: editForm.matched_topics,
          notes: editForm.notes,
        },
      ]);
      setEditingId(null);
      setEditForm(null);
      setMessage("导师标签和状态已保存，并已按标签重新评分。");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存导师标签失败。");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRescore() {
    setRescoring(true);
    setMessage("");
    setError("");
    try {
      const result = await api.rescoreProfessors();
      setMessage(`已按当前标签和偏好重新评分 ${result.updated} 位导师。`);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新评分失败。");
    } finally {
      setRescoring(false);
    }
  }

  function openEdit(row: Professor) {
    setEditingId(row.id);
    setEditForm(editFormFromProfessor(row));
    setMessage("");
    setError("");
  }

  function exportCsv() {
    const escapeCell = (value: unknown) => {
      const text = String(value ?? "");
      const safe = /^[\s]*[=+\-@\t\r\n]/.test(text) ? `'${text}` : text;
      return `"${safe.replace(/"/g, '""')}"`;
    };
    const headers = ["姓名", "学校", "学院", "邮箱", "主页", "研究方向", "联系状态", "下次跟进", "下一步计划", "上次联系", "上次回复", "备注"];
    const lines = [headers, ...rows.map((row) => [row.name, row.school, row.institute, row.email, row.profile_url, row.research_summary, contactStageLabel(row.contact_stage), row.next_follow_up, row.next_action, row.last_contacted_at, row.last_replied_at, row.notes])];
    const url = URL.createObjectURL(new Blob(["\uFEFF", lines.map((line) => line.map(escapeCell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8;" }));
    const link = document.createElement("a"); link.href = url; link.download = `autosocial-mentors-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    setMessage(`已导出当前筛选的 ${rows.length} 位导师。`);
  }

  return (
    <div className="page-stack page-stack-tight mentor-pool-page">
      <SectionCard
        title="导师池"
        actions={
          <div className="inline-actions">
            <button className="ghost-button" onClick={exportCsv} disabled={!rows.length} type="button">导出 CSV</button>
            <button className="ghost-button" disabled={rescoring} onClick={handleRescore} type="button">
              {rescoring ? "评分中..." : "按标签重新评分"}
            </button>
            <button className="primary-button" onClick={onCreateProfessor} type="button">
              新增老师
            </button>
          </div>
        }
      >
        <div className="mentor-stats mentor-stats-extended">
          <button className={filter === "all" ? "mentor-stat active" : "mentor-stat"} onClick={() => setFilter("all")} type="button">
            <span>全部</span>
            <strong>{stats.total}</strong>
          </button>
          <button className={filter === "replied" ? "mentor-stat active" : "mentor-stat"} onClick={() => setFilter("replied")} type="button">
            <span>已回复</span>
            <strong>{stats.replied}</strong>
          </button>
          <button className={filter === "contacted" ? "mentor-stat active" : "mentor-stat"} onClick={() => setFilter("contacted")} type="button">
            <span>已联系</span>
            <strong>{stats.contacted}</strong>
          </button>
          <button className={filter === "ready" ? "mentor-stat active" : "mentor-stat"} onClick={() => setFilter("ready")} type="button">
            <span>信息较全</span>
            <strong>{stats.ready}</strong>
          </button>
          <button className={filter === "missing" ? "mentor-stat active" : "mentor-stat"} onClick={() => setFilter("missing")} type="button">
            <span>待补全</span>
            <strong>{stats.missing}</strong>
          </button>
          <button className={filter === "draft" ? "mentor-stat active" : "mentor-stat"} onClick={() => setFilter("draft")} type="button">
            <span>有草稿</span>
            <strong>{stats.draft}</strong>
          </button>
        </div>

        <div className="simple-toolbar">
          <input
            className="search-input"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="搜索姓名 / 学校 / 邮箱 / 方向 / 标签 / 状态"
          />
          <div className="simple-toolbar-meta">
            <span>{rows.length} 位导师</span>
            <label>
              排序
              <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
                <option value="priority">进度优先</option>
                <option value="updated">最近更新</option>
                <option value="completeness">信息完整</option>
                <option value="school">学校姓名</option>
              </select>
            </label>
          </div>
        </div>

        {message ? <div className="success-box">{message}</div> : null}
        {error ? <div className="error-box">{error}</div> : null}

        {!rows.length ? (
          <div className="empty-state">{professors.length ? "没有符合当前筛选条件的导师。请调整搜索或筛选条件。" : "还没有导师。点击“新增老师”即可加入导师池。"}</div>
        ) : (
          <div className="mentor-card-grid">
            {rows.map((row) => {
              const completeness = professorCompleteness(row);
              const topics = topicList(row);
              const isEditing = editingId === row.id && editForm;
              return (
                <article className="mentor-card" key={row.id}>
                  <div className="mentor-card-head">
                    <div>
                      <strong>{row.name || "未填写姓名"}</strong>
                      <p>
                        {row.school || "学校未填"}
                        {row.institute ? ` / ${row.institute}` : ""}
                      </p>
                    </div>
                    <button className="primary-button small-button" onClick={() => onUseProfessor(row.id)} type="button">
                      用于写信
                    </button>
                  </div>

                  <div className="mentor-completeness">
                    <span>信息 {completeness.filled}/{completeness.total}</span>
                    <div>
                      <i style={{ width: `${completeness.percent}%` }} />
                    </div>
                  </div>

                  <div className="mentor-tags">
                    <StatusBadge text={contactStageLabel(row.contact_stage)} tone={contactStageTone(row.contact_stage)} />
                    <StatusBadge text={verificationLabel(row.verification_status)} tone={verificationTone(row.verification_status)} />
                    <StatusBadge text={fitLabelText(row.fit_label)} tone={fitTone(row.fit_label)} />
                    {row.shortlisted ? <StatusBadge text="已心仪" tone="good" /> : null}
                    {row.draft_status ? <StatusBadge text={row.draft_status === "sent" ? "已发送" : "有草稿"} tone="neutral" /> : null}
                  </div>

                  {topics.length ? (
                    <div className="mentor-topic-list">
                      {topics.slice(0, 6).map((topic) => (
                        <span key={topic}>{topic}</span>
                      ))}
                    </div>
                  ) : null}

                  <div className="mentor-meta-list">
                    <span>{row.email || "邮箱未填"}</span>
                    <span>{row.title || "职称未填"}</span>
                    <span>评分 {Math.round(row.fit_score || 0)}</span>
                    <span>优先级 {Math.round(progressPriority(row))}</span>
                    <span>更新于 {formatDateShort(row.updated_at || row.created_at)}</span>
                  </div>

                  <p className="mentor-research">{row.research_summary || "暂无研究方向，建议在写信页补充后再生成草稿。"}</p>

                  {row.notes?.trim() ? (
                    <div className="mentor-note-preview">
                      <span>
                        备注
                        {row.note_priority_score ? ` · ${row.note_priority_score > 0 ? "+" : ""}${Math.round(row.note_priority_score)}` : ""}
                        {row.note_priority_source === "ai" ? " · AI" : ""}
                      </span>
                      <p>{row.notes}</p>
                    </div>
                  ) : null}

                  {isEditing ? (
                    <div className="mentor-edit-panel">
                      <label>
                        联系状态
                        <select
                          value={editForm.contact_stage}
                          onChange={(event) => setEditForm({ ...editForm, contact_stage: event.target.value })}
                        >
                          {CONTACT_STAGE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        核验状态
                        <select
                          value={editForm.verification_status}
                          onChange={(event) => setEditForm({ ...editForm, verification_status: event.target.value })}
                        >
                          {VERIFICATION_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="mentor-checkbox-label">
                        <input
                          checked={editForm.shortlisted}
                          onChange={(event) => setEditForm({ ...editForm, shortlisted: event.target.checked })}
                          type="checkbox"
                        />
                        标记为心仪导师
                      </label>
                      <label className="mentor-edit-wide">
                        自定义标签 / 方向关键词
                        <input
                          value={editForm.matched_topics}
                          onChange={(event) => setEditForm({ ...editForm, matched_topics: event.target.value })}
                          placeholder="用 |、逗号或顿号分隔方向关键词与自定义标签"
                        />
                      </label>
                      <label className="mentor-edit-wide">
                        备注
                        <textarea value={editForm.notes} onChange={(event) => setEditForm({ ...editForm, notes: event.target.value })} />
                      </label>
                      <div className="mentor-edit-actions">
                        <button className="primary-button small-button" disabled={busyId === row.id} onClick={() => handleSaveEdit(row)} type="button">
                          {busyId === row.id ? "保存中..." : "保存标签"}
                        </button>
                        <button
                          className="ghost-button small-button"
                          onClick={() => {
                            setEditingId(null);
                            setEditForm(null);
                          }}
                          type="button"
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  ) : null}

                  <div className="mentor-actions">
                    <button className="ghost-button small-button" onClick={() => openEdit(row)} type="button">
                      编辑标签
                    </button>
                    <button className="ghost-button small-button" onClick={() => onUseProfessor(row.id)} type="button">
                      编辑资料
                    </button>
                    <button className="ghost-button small-button danger-button" disabled={busyId === row.id} onClick={() => handleMoveToTrash(row)} type="button">
                      {busyId === row.id ? "移动中..." : "移入垃圾桶"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
