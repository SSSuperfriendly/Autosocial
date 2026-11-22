import { useMemo, useState } from "react";

import { api } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";
import type { Professor } from "../types";
import {
  contactStageLabel,
  contactStageTone,
  fitLabelText,
  fitTone,
  formatDateShort,
  verificationLabel,
  verificationTone,
} from "../utils/labels";
import { isCleanProfessor, matchProfessor, professorCompleteness } from "../utils/mentor";

type Props = {
  professors: Professor[];
  onChanged: () => void | Promise<void>;
};

function topicList(row: Professor) {
  return String(row.matched_topics || "")
    .split("|")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function TrashPage({ professors, onChanged }: Props) {
  const [searchTerm, setSearchTerm] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const normalizedSearch = searchTerm.trim().toLowerCase();

  const rows = useMemo(
    () =>
      professors
        .filter((row) => matchProfessor(row, normalizedSearch))
        .sort((a, b) => Date.parse(b.trashed_at || "") - Date.parse(a.trashed_at || "")),
    [professors, normalizedSearch],
  );

  async function handleRestore(row: Professor) {
    setBusyId(row.id);
    setMessage("");
    setError("");
    try {
      await api.restoreProfessors([row.id]);
      setMessage("导师已移回导师池。");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "移回导师池失败。");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(row: Professor) {
    const confirmed = window.confirm(
      `确认彻底删除 ${row.name || "这位导师"} 吗？删除后导师资料、草稿、发信记录和回信记录都会一起删除，无法从垃圾桶恢复。`,
    );
    if (!confirmed) return;

    setBusyId(row.id);
    setMessage("");
    setError("");
    try {
      await api.deleteProfessors([row.id]);
      setMessage("导师已彻底删除。");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "彻底删除失败。");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="page-stack page-stack-tight trash-page">
      <SectionCard title="回收站">
        <div className="simple-toolbar">
          <input
            className="search-input"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="搜索已淘汰导师的姓名 / 学校 / 邮箱 / 方向 / 标签"
          />
          <div className="simple-toolbar-meta">
            <span>{rows.length} 位导师</span>
          </div>
        </div>

        {message ? <div className="success-box">{message}</div> : null}
        {error ? <div className="error-box">{error}</div> : null}

        {!rows.length ? (
          <div className="empty-state">垃圾桶为空。导师池里点击“移入垃圾桶”后，会在这里集中查看和恢复。</div>
        ) : (
          <div className="mentor-card-grid">
            {rows.map((row) => {
              const completeness = professorCompleteness(row);
              const topics = topicList(row);
              return (
                <article className="mentor-card trash-mentor-card" key={row.id}>
                  <div className="mentor-card-head">
                    <div>
                      <strong>{row.name || "未填写姓名"}</strong>
                      <p>
                        {row.school || "学校未填"}
                        {row.institute ? ` / ${row.institute}` : ""}
                      </p>
                    </div>
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
                    <StatusBadge text="已移入垃圾桶" tone="danger" />
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
                    <span>移入于 {formatDateShort(row.trashed_at)}</span>
                  </div>

                  <p className="mentor-research">{row.research_summary || "暂无研究方向。"}</p>

                  {row.notes?.trim() ? (
                    <div className="mentor-note-preview">
                      <span>备注</span>
                      <p>{row.notes}</p>
                    </div>
                  ) : null}

                  <div className="mentor-actions">
                    <button className="primary-button small-button" disabled={busyId === row.id} onClick={() => handleRestore(row)} type="button">
                      {busyId === row.id ? "移动中..." : "移入导师池"}
                    </button>
                    <button className="ghost-button small-button danger-button" disabled={busyId === row.id} onClick={() => handleDelete(row)} type="button">
                      {busyId === row.id ? "删除中..." : "彻底删除"}
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
