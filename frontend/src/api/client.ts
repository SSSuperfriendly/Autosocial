import type { ContactEvent, DiscoveryResult, Draft, Metrics, Preferences, Professor, Reply, SystemStatus } from "../types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}），请稍后重试。`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") message = payload.detail;
      else if (Array.isArray(payload.detail)) {
        message = payload.detail.map((item: { loc?: string[]; msg?: string }) => `${item.loc?.slice(1).join(".") || "输入"}：${item.msg || "格式不正确"}`).join("；");
      }
    } catch { /* Keep the readable fallback for proxy and server errors. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  tracking: () => request<{ professors: Professor[]; events: ContactEvent[] }>("/api/tracking"),
  updateTracking: (professorId: number, payload: { contact_stage?: string; next_follow_up?: string | null; next_action?: string | null }) =>
    request<{ professor: Professor }>(`/api/tracking/${professorId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  addContactEvent: (professorId: number, payload: { kind: ContactEvent["kind"]; content: string; occurred_at?: string }) =>
    request<{ professor: Professor; event: ContactEvent }>(`/api/tracking/${professorId}/events`, { method: "POST", body: JSON.stringify(payload) }),
  deleteContactEvent: (eventId: number) => request<{ ok: boolean }>(`/api/tracking/events/${eventId}`, { method: "DELETE" }),
  health: () => request<{ ok: boolean }>("/health"),
  metrics: () => request<Metrics>("/api/overview/metrics"),
  systemStatus: () => request<SystemStatus>("/api/system/status"),
  preferences: () => request<Preferences>("/api/preferences"),
  savePreferences: (data: Preferences) =>
    request<Preferences>("/api/preferences", { method: "PUT", body: JSON.stringify({ data }) }),
  studentProfile: () => request<{ content: string }>("/api/preferences/student-profile"),
  saveStudentProfile: (content: string) =>
    request<{ ok: boolean }>("/api/preferences/student-profile", {
      method: "PUT",
      body: JSON.stringify({ content })
    }),
  emailTemplate: () => request<{ content: string }>("/api/preferences/email-template"),
  saveEmailTemplate: (content: string) =>
    request<{ ok: boolean }>("/api/preferences/email-template", {
      method: "PUT",
      body: JSON.stringify({ content })
    }),
  targets: () => request<{ rows: Array<Record<string, string>> }>("/api/preferences/targets"),
  saveTargets: (rows: Array<Record<string, string>>) =>
    request<{ ok: boolean }>("/api/preferences/targets", {
      method: "PUT",
      body: JSON.stringify({ rows })
    }),
  prompts: () => request<{ rows: Array<Record<string, string | boolean>> }>("/api/preferences/prompts"),
  savePrompts: (rows: Array<Record<string, string | boolean>>) =>
    request<{ ok: boolean }>("/api/preferences/prompts", {
      method: "PUT",
      body: JSON.stringify({ rows })
    }),
  professors: () => request<{ rows: Professor[] }>("/api/professors"),
  trashProfessorsList: () => request<{ rows: Professor[] }>("/api/professors?trashed_only=true"),
  saveProfessors: (rows: Professor[]) =>
    request<{ ok: boolean }>("/api/professors", { method: "PUT", body: JSON.stringify({ rows }) }),
  trashProfessors: (professorIds: number[]) =>
    request<{ moved: number }>("/api/professors/trash", {
      method: "POST",
      body: JSON.stringify({ professor_ids: professorIds })
    }),
  restoreProfessors: (professorIds: number[]) =>
    request<{ restored: number }>("/api/professors/restore", {
      method: "POST",
      body: JSON.stringify({ professor_ids: professorIds })
    }),
  deleteProfessors: (professorIds: number[]) =>
    request<{ deleted: number }>("/api/professors/delete", {
      method: "POST",
      body: JSON.stringify({ professor_ids: professorIds })
    }),
  rescoreProfessors: () => request<{ updated: number }>("/api/professors/rescore", { method: "POST" }),
  drafts: () => request<{ rows: Draft[] }>("/api/drafts"),
  saveDrafts: (rows: Draft[]) =>
    request<{ ok: boolean }>("/api/drafts", { method: "PUT", body: JSON.stringify({ rows }) }),
  generateDrafts: (professorIds: number[], autoApprove: boolean, thinkingMode: "conservative" | "proactive") =>
    request<{ generated: number }>("/api/drafts/generate", {
      method: "POST",
      body: JSON.stringify({
        professor_ids: professorIds,
        auto_approve: autoApprove,
        thinking_mode: thinkingMode
      })
    }),
  runDiscovery: (payload: {
    backend: string;
    schools: string[];
    limit_per_school: number;
    max_crawl_pages: number;
    max_crawl_depth: number;
  }) =>
    request<DiscoveryResult>("/api/discovery/run", { method: "POST", body: JSON.stringify(payload) }),
  createDiscoveryTask: (payload: {
    backend: string;
    schools: string[];
    limit_per_school: number;
    max_crawl_pages: number;
    max_crawl_depth: number;
  }) =>
    request<{ task_id: string }>("/api/discovery/tasks", { method: "POST", body: JSON.stringify(payload) }),
  getDiscoveryTask: (taskId: string) =>
    request<{
      task_id: string;
      status: string;
      progress: number;
      events: Array<Record<string, unknown>>;
      result: DiscoveryResult | null;
      error: string | null;
    }>(`/api/discovery/tasks/${taskId}`),
  send: (professorIds: number[], autoPrepare: boolean, dryRun: boolean) =>
    request<{
      processed: number;
      sent: number;
      skipped: number;
      failures: Array<Record<string, string>>;
      safety_mode: string;
      test_recipient_email?: string | null;
    }>(
      "/api/outreach/send",
      {
        method: "POST",
        body: JSON.stringify({
          professor_ids: professorIds,
          auto_prepare: autoPrepare,
          dry_run: dryRun
        })
      }
    ),
  syncReplies: (days: number) =>
    request<{ total: number }>("/api/outreach/replies/sync", {
      method: "POST",
      body: JSON.stringify({ days })
    }),
  replies: () => request<{ rows: Reply[] }>("/api/outreach/replies"),
  generateWriterDraft: (payload: {
    professor_id?: number | null;
    name: string;
    email: string;
    school: string;
    institute: string;
    title: string;
    profile_url: string;
    research_summary: string;
    professor_intro: string;
    notes: string;
    thinking_mode: "conservative" | "proactive";
  }) =>
    request<{ professor: Professor; draft: Draft }>("/api/writer/draft", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  saveWriterDraft: (payload: { draft_id: number; professor_id: number; subject: string; body: string }) =>
    request<{ draft: Draft }>("/api/writer/draft/save", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  saveWriterProfessor: (payload: {
    professor_id?: number | null;
    name: string;
    email: string;
    school: string;
    institute: string;
    title: string;
    profile_url: string;
    research_summary: string;
    professor_intro: string;
    notes: string;
    thinking_mode: "conservative" | "proactive";
  }) =>
    request<{ professor: Professor }>("/api/writer/professor", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  startBrowserSession: (page: string) =>
    request<{ session_id: string; active_sessions: number; started_at: string }>("/api/system/browser-session/start", {
      method: "POST",
      body: JSON.stringify({ page })
    }),
  heartbeatBrowserSession: (sessionId: string, page: string) =>
    request<{ active_sessions: number }>("/api/system/browser-session/heartbeat", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, page })
    }),
  endBrowserSession: (sessionId: string) =>
    request<{ active_sessions: number }>("/api/system/browser-session/end", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId })
    }),
};
