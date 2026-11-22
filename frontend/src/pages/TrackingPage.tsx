import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import type { ContactEvent, Professor } from "../types";
import { CONTACT_STAGE_OPTIONS, contactStageLabel, contactStageTone, formatDate } from "../utils/labels";
import { matchProfessor } from "../utils/mentor";
import "../tracking.css";

type Props = {
  professors: Professor[];
  events: ContactEvent[];
  loading: boolean;
  onChanged: () => Promise<void>;
  onCreate: () => void;
  onWrite: (id: number) => void;
  onSettings: () => void;
};
type DueFilter = "today" | "overdue" | "upcoming" | "all";
const EVENT_LABELS: Record<ContactEvent["kind"], string> = { note: "备忘", email_sent: "已联系", reply: "收到回复", meeting: "面谈 / 面试" };
function localDay(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function active(row: Professor) { return row.contact_stage !== "rejected"; }

export function TrackingPage({ professors, events, loading, onChanged, onCreate, onWrite, onSettings }: Props) {
  const [dueFilter, setDueFilter] = useState<DueFilter>("all");
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [followUp, setFollowUp] = useState("");
  const [nextAction, setNextAction] = useState("");
  const [contactStage, setContactStage] = useState("new");
  const [eventKind, setEventKind] = useState<ContactEvent["kind"]>("note");
  const [eventContent, setEventContent] = useState("");
  const [eventDate, setEventDate] = useState(localDay);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const planBaselineRef = useRef<{ id: number; date: string; action: string; stage: string } | null>(null);
  const today = localDay();
  const nextWeek = new Date();
  nextWeek.setDate(nextWeek.getDate() + 7);
  const weekEnd = localDay(nextWeek);
  const selected = professors.find((row) => row.id === selectedId);
  useEffect(() => {
    const baseline = planBaselineRef.current;
    if (!selected || !baseline || baseline.id !== selected.id) return;
    const next = { id: selected.id, date: selected.next_follow_up || "", action: selected.next_action || "", stage: selected.contact_stage };
    setFollowUp((current) => current === baseline.date ? next.date : current);
    setNextAction((current) => current === baseline.action ? next.action : current);
    setContactStage((current) => current === baseline.stage ? next.stage : current);
    planBaselineRef.current = next;
  }, [selected?.id, selected?.next_follow_up, selected?.next_action, selected?.contact_stage]);
  const counts = {
    today: professors.filter((row) => active(row) && row.next_follow_up === today).length,
    overdue: professors.filter((row) => active(row) && row.next_follow_up && row.next_follow_up < today).length,
    upcoming: professors.filter((row) => active(row) && row.next_follow_up && row.next_follow_up > today && row.next_follow_up <= weekEnd).length,
    all: professors.length,
  };
  const rows = useMemo(() => professors.filter((row) => {
    if (!matchProfessor(row, search.trim().toLowerCase())) return false;
    if (stage && row.contact_stage !== stage) return false;
    if (dueFilter === "all") return true;
    if (!active(row) || !row.next_follow_up) return false;
    if (dueFilter === "today") return row.next_follow_up === today;
    if (dueFilter === "overdue") return row.next_follow_up < today;
    return row.next_follow_up > today && row.next_follow_up <= weekEnd;
  }).sort((a, b) => {
    const left = active(a) ? a.next_follow_up || "9999" : "9999";
    const right = active(b) ? b.next_follow_up || "9999" : "9999";
    return left.localeCompare(right) || (b.shortlisted ? 1 : 0) - (a.shortlisted ? 1 : 0) || (a.name || "").localeCompare(b.name || "", "zh-CN");
  }), [professors, search, stage, dueFilter, today, weekEnd]);
  const selectedEvents = events.filter((event) => event.professor_id === selectedId).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at) || b.id - a.id);
  const recentEvents = [...events].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)).slice(0, 5);

  function openProfessor(row: Professor) {
    if (busy) return;
    if (selected && (followUp !== (selected.next_follow_up || "") || nextAction !== (selected.next_action || "") || contactStage !== selected.contact_stage || eventContent.trim()) && !window.confirm("当前跟进计划或沟通记录有未保存内容，确定切换导师吗？")) return;
    setSelectedId(row.id);
    planBaselineRef.current = { id: row.id, date: row.next_follow_up || "", action: row.next_action || "", stage: row.contact_stage };
    setFollowUp(row.next_follow_up || "");
    setNextAction(row.next_action || "");
    setContactStage(row.contact_stage);
    setEventContent("");
    setMessage(""); setError("");
  }
  async function saveTracking() {
    if (!selected) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await api.updateTracking(selected.id, { next_follow_up: followUp || null, next_action: nextAction.trim() || null, contact_stage: contactStage });
      await onChanged(); setMessage("跟进计划已保存。");
    } catch (err) { setError(err instanceof Error ? err.message : "保存失败，请重试。"); }
    finally { setBusy(false); }
  }
  async function addEvent() {
    if (!selected || !eventContent.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api.addContactEvent(selected.id, { kind: eventKind, content: eventContent.trim(), occurred_at: eventDate ? new Date(`${eventDate}T12:00:00`).toISOString() : undefined });
      setContactStage(result.professor.contact_stage);
      setEventContent(""); await onChanged(); setMessage("沟通记录已保存。");
    } catch (err) { setError(err instanceof Error ? err.message : "记录失败，请重试。"); }
    finally { setBusy(false); }
  }
  async function deleteEvent(id: number) {
    if (!window.confirm("删除这条沟通记录？删除后会更新最近沟通时间，当前联系状态会保留。")) return;
    setBusy(true); setError(""); setMessage("");
    try { await api.deleteContactEvent(id); await onChanged(); setMessage("记录已删除。"); }
    catch (err) { setError(err instanceof Error ? err.message : "删除失败，请重试。"); }
    finally { setBusy(false); }
  }

  return (
    <div className="tracking-page">
      <section className="tracking-heading">
        <div><p className="tracking-eyebrow">YOUR PHD JOURNEY</p><h2>申请路上，有条不紊。</h2><p>记住每一位导师，也记住下一次联系。</p></div>
        <button className="primary-button" onClick={onCreate} type="button">＋ 添加导师</button>
      </section>
      {!loading && professors.length === 0 ? <section className="tracking-welcome">
        <div><h3>从第一位意向导师开始</h3><p>添加导师、记录沟通、设定下次跟进日期。基础管理无需 API Key，数据保存在你自己的服务中。</p>
          <div className="inline-actions"><button className="primary-button" onClick={onCreate} type="button">添加第一位导师</button><button className="ghost-button" onClick={onSettings} type="button">完善申请者资料</button></div>
        </div>
      </section> : null}
      <div className="tracking-stats" aria-label="跟进概览">
        {([{ key: "today", title: "今天跟进", detail: "把计划变成行动" }, { key: "overdue", title: "已逾期", detail: "重新安排联系时间" }, { key: "upcoming", title: "未来 7 天", detail: "提前准备下一次沟通" }, { key: "all", title: "全部导师", detail: "你的申请联系人" }] as const).map((item) =>
          <button key={item.key} type="button" className={`tracking-stat ${dueFilter === item.key ? "is-active" : ""} ${item.key === "overdue" && counts.overdue ? "has-overdue" : ""}`} onClick={() => setDueFilter(item.key)} aria-pressed={dueFilter === item.key}>
            <span>{item.title}</span><strong>{counts[item.key]}</strong><small>{item.detail}</small>
          </button>)}
      </div>
      <div className="tracking-columns">
        <section className="section-card tracking-list-section">
          <div className="section-header"><div><h2>跟进清单</h2><p className="tracking-muted">按下次跟进日期排列 · 记录外部邮件与面试进展</p></div><span className="tracking-count">{rows.length} 位</span></div>
          <div className="tracking-toolbar">
            <input aria-label="搜索导师" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索导师、学校、方向或备注" />
            <select aria-label="筛选联系状态" value={stage} onChange={(event) => setStage(event.target.value)}><option value="">全部联系状态</option>{CONTACT_STAGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
          </div>
          {rows.length ? <div className="tracking-list">{rows.map((row) => {
            const overdue = active(row) && row.next_follow_up && row.next_follow_up < today;
            return <button className={`tracking-row ${selectedId === row.id ? "is-selected" : ""}`} key={row.id} type="button" disabled={busy} onClick={() => openProfessor(row)}>
              <div className="tracking-avatar" aria-hidden="true">{(row.name || "?").slice(0, 1)}</div>
              <div className="tracking-row-main"><strong>{row.name || "未填写姓名"}{row.shortlisted ? <span className="tracking-favorite" aria-label="心仪导师">★</span> : null}</strong><span>{row.school || "学校未填写"}{row.institute ? ` · ${row.institute}` : ""}</span><p>{row.next_action || "添加下一步计划，让跟进更清晰"}</p></div>
              <div className="tracking-row-state"><StatusBadge text={contactStageLabel(row.contact_stage)} tone={contactStageTone(row.contact_stage)} /><small className={overdue ? "tracking-overdue" : ""}>{row.next_follow_up ? `${overdue ? "逾期 · " : row.next_follow_up === today ? "今天 · " : ""}${row.next_follow_up}` : "未安排跟进"}</small></div>
            </button>;
          })}</div> : <div className="empty-state">{loading ? "正在加载导师…" : professors.length ? "当前条件下没有导师。试试其他日期或联系状态。" : "添加导师后，在这里安排你的第一项跟进。"}</div>}
        </section>
        <aside className="tracking-detail">
          {selected ? <section className="section-card">
            <div className="section-header"><div><h2>{selected.name || "导师详情"}</h2><p className="tracking-muted">{selected.school}</p></div><button className="ghost-button small-button" onClick={() => onWrite(selected.id)} disabled={busy} type="button">资料与写信</button></div>
            {message ? <div className="success-box" role="status">{message}</div> : null}{error ? <div className="error-box" role="alert">{error}</div> : null}
            <div className="tracking-plan"><h3>下一步计划</h3>
              <div className="tracking-form-grid"><label>联系状态<select disabled={busy} value={contactStage} onChange={(event) => setContactStage(event.target.value)}>{CONTACT_STAGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label><label>下次跟进<input disabled={busy} type="date" value={followUp} onChange={(event) => setFollowUp(event.target.value)} /></label></div>
              <label>下一步要做什么<input disabled={busy} value={nextAction} maxLength={1000} onChange={(event) => setNextAction(event.target.value)} placeholder="例如：阅读论文后发送研究计划" /></label>
              <button className="primary-button" onClick={saveTracking} disabled={busy} type="button">{busy ? "处理中…" : "保存跟进计划"}</button>
            </div>
            <div className="tracking-event-form"><h3>记录一次沟通</h3><p className="tracking-muted">仅记录已经发生的沟通，不会发送邮件。</p>
              <div className="tracking-form-grid"><label>沟通类型<select disabled={busy} value={eventKind} onChange={(event) => setEventKind(event.target.value as ContactEvent["kind"])}>{Object.entries(EVENT_LABELS).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label><label>发生日期<input disabled={busy} type="date" value={eventDate} onChange={(event) => setEventDate(event.target.value)} /></label></div>
              <label>沟通内容<textarea disabled={busy} value={eventContent} maxLength={10000} onChange={(event) => setEventContent(event.target.value)} placeholder="记录邮件要点、导师反馈、面试感受或待办事项" /></label>
              <button className="ghost-button" type="button" onClick={addEvent} disabled={busy || !eventContent.trim()}>添加沟通记录</button>
            </div>
            <div className="tracking-timeline"><h3>沟通时间线 <span>{selectedEvents.length}</span></h3>
              {selectedEvents.length ? selectedEvents.map((event) => <article className="tracking-event" key={event.id}><div><span>{EVENT_LABELS[event.kind]}</span><time>{formatDate(event.occurred_at)}</time><button type="button" className="tracking-delete" aria-label="删除沟通记录" onClick={() => deleteEvent(event.id)} disabled={busy}>删除</button></div><p>{event.content}</p></article>) : <p className="tracking-muted">还没有沟通记录。添加第一条，让进展有迹可循。</p>}
            </div>
          </section> : <section className="section-card tracking-activity"><p className="tracking-eyebrow">RECENT ACTIVITY</p><h2>最近的进展</h2>
            {recentEvents.length ? recentEvents.map((event) => <button type="button" className="tracking-activity-item" key={event.id} onClick={() => { const row = professors.find((p) => p.id === event.professor_id); if (row) openProfessor(row); }}><span>{EVENT_LABELS[event.kind]} · {event.professor_name || professors.find((p) => p.id === event.professor_id)?.name || "导师"}</span><p>{event.content}</p><small>{formatDate(event.occurred_at)}</small></button>) : <div className="tracking-quiet"><span aria-hidden="true">◎</span><p>选择一位导师，安排下一步，<br />或记录刚刚发生的沟通。</p></div>}
            <p className="tracking-muted tracking-tip">小建议：每次沟通后，给自己留一个明确的下一步。</p>
          </section>}
        </aside>
      </div>
    </div>
  );
}
