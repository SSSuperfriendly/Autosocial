import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api/client";
import { Layout, type TabKey } from "./components/Layout";
import { TrackingPage } from "./pages/TrackingPage";
import { DiscoveryPage } from "./pages/DiscoveryPage";
import { MentorPoolPage } from "./pages/MentorPoolPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TrashPage } from "./pages/TrashPage";
import { WriterPage } from "./pages/WriterPage";
import type { ContactEvent, Preferences, Professor, SystemStatus, TargetSchoolRow } from "./types";

export default function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("tracking");
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [contactEvents, setContactEvents] = useState<ContactEvent[]>([]);
  const [writerDirty, setWriterDirty] = useState(false);
  const [professors, setProfessors] = useState<Professor[]>([]);
  const [trashProfessors, setTrashProfessors] = useState<Professor[]>([]);
  const [targetRows, setTargetRows] = useState<TargetSchoolRow[]>([]);
  const [studentProfile, setStudentProfile] = useState("");
  const [emailTemplate, setEmailTemplate] = useState("");
  const [error, setError] = useState("");
  const [selectedProfessorId, setSelectedProfessorId] = useState<number | null>(null);
  const [selectedProfessorLoadKey, setSelectedProfessorLoadKey] = useState(0);
  const [writerResetKey, setWriterResetKey] = useState(0);
  const sessionIdRef = useRef<string>("");

  const loadAll = useCallback(async () => {
    setError("");
    const results = await Promise.allSettled([
      api.tracking(), api.preferences(), api.trashProfessorsList(), api.targets(),
      api.studentProfile(), api.emailTemplate(), api.systemStatus()
    ]);
    const [tracking, prefs, trash, targets, profile, template, status] = results;
    if (tracking.status === "fulfilled") {
      setProfessors(tracking.value.professors);
      setContactEvents(tracking.value.events);
    }
    if (prefs.status === "fulfilled") setPreferences(prefs.value);
    if (trash.status === "fulfilled") setTrashProfessors(trash.value.rows);
    if (targets.status === "fulfilled") setTargetRows(targets.value.rows as TargetSchoolRow[]);
    if (profile.status === "fulfilled") setStudentProfile(profile.value.content);
    if (template.status === "fulfilled") setEmailTemplate(template.value.content);
    if (status.status === "fulfilled") setSystemStatus(status.value);
    const failed = results.find((result) => result.status === "rejected");
    if (failed?.status === "rejected") setError(failed.reason instanceof Error ? failed.reason.message : "部分数据加载失败，请重试。");
    setLoading(false);
  }, []);

  function changeTab(tab: TabKey) {
    if (activeTab === "drafts" && tab !== "drafts" && writerDirty && !window.confirm("写信页有未保存的内容。内容会暂存于当前页面，确定切换吗？")) return;
    setActiveTab(tab);
  }

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    let disposed = false;
    let heartbeatTimer: number | null = null;

    const pathname = window.location.pathname || "/";

    const flushSession = () => {
      const sessionId = sessionIdRef.current;
      if (!sessionId) return;
      const payload = JSON.stringify({ session_id: sessionId });
      if (navigator.sendBeacon) {
        const blob = new Blob([payload], { type: "application/json" });
        navigator.sendBeacon("/api/system/browser-session/end", blob);
      } else {
        fetch("/api/system/browser-session/end", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: payload,
          keepalive: true,
        }).catch(() => undefined);
      }
    };

    async function startSession() {
      try {
        const result = await api.startBrowserSession(pathname);
        if (disposed) {
          await api.endBrowserSession(result.session_id).catch(() => undefined);
          return;
        }
        sessionIdRef.current = result.session_id;
        heartbeatTimer = window.setInterval(() => {
          if (!sessionIdRef.current) return;
          api.heartbeatBrowserSession(sessionIdRef.current, window.location.pathname || "/").catch(() => undefined);
        }, 15000);
      } catch {
      }
    }

    const handlePageHide = () => flushSession();
    const handleBeforeUnload = () => flushSession();

    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("beforeunload", handleBeforeUnload);
    startSession();

    return () => {
      disposed = true;
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("beforeunload", handleBeforeUnload);
      if (heartbeatTimer != null) window.clearInterval(heartbeatTimer);
      flushSession();
    };
  }, []);

  return (
    <Layout activeTab={activeTab} onTabChange={changeTab}>
      {error ? <div className="error-box" role="alert">{error} <button className="ghost-button small-button" onClick={loadAll} type="button">重新加载</button></div> : null}
      {loading ? <div className="empty-state" role="status">正在加载申请工作台…</div> : null}
      <div hidden={activeTab !== "tracking"}>
        <TrackingPage professors={professors} events={contactEvents} loading={loading} onChanged={loadAll}
          onCreate={() => { setSelectedProfessorId(null); setWriterResetKey((key) => key + 1); changeTab("drafts"); }}
          onWrite={(id) => { setSelectedProfessorId(id); setSelectedProfessorLoadKey((key) => key + 1); changeTab("drafts"); }}
          onSettings={() => changeTab("settings")} />
      </div>
      <div hidden={activeTab !== "discovery"}>
        <DiscoveryPage preferences={preferences} systemStatus={systemStatus} targetRows={targetRows} onDiscoveryFinished={loadAll} />
      </div>
      <div hidden={activeTab !== "pool"}>
        <MentorPoolPage professors={professors}
          onCreateProfessor={() => { setSelectedProfessorId(null); setWriterResetKey((key) => key + 1); changeTab("drafts"); }}
          onUseProfessor={(id) => { setSelectedProfessorId(id); setSelectedProfessorLoadKey((key) => key + 1); changeTab("drafts"); }}
          onChanged={loadAll} />
      </div>
      <div hidden={activeTab !== "trash"}><TrashPage professors={trashProfessors} onChanged={loadAll} /></div>
      <div hidden={activeTab !== "drafts"}>
        <WriterPage professors={professors} selectedProfessorId={selectedProfessorId} selectedProfessorLoadKey={selectedProfessorLoadKey}
          resetKey={writerResetKey} onDirtyChange={setWriterDirty}
          onNewProfessor={() => { setSelectedProfessorId(null); setWriterResetKey((key) => key + 1); }} onGenerated={loadAll} />
      </div>
      <div hidden={activeTab !== "settings"}>
        <SettingsPage targetRows={targetRows} studentProfile={studentProfile} emailTemplate={emailTemplate} systemStatus={systemStatus} onSaved={loadAll} />
      </div>
    </Layout>
  );
}
