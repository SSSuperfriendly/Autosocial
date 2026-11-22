import type { Professor } from "../types";

export type WriterFormState = {
  professor_id: number | null;
  name: string;
  email: string;
  school: string;
  institute: string;
  title: string;
  profile_url: string;
  research_summary: string;
  professor_intro: string;
  notes: string;
};

export const EMPTY_WRITER_FORM: WriterFormState = {
  professor_id: null,
  name: "",
  email: "",
  school: "",
  institute: "",
  title: "",
  profile_url: "",
  research_summary: "",
  professor_intro: "",
  notes: "",
};

export function isCleanProfessor(row: Professor) {
  const text = [row.name, row.school, row.institute].filter(Boolean).join(" ");
  if (!text.trim()) return false;
  return !/[?]{2,}/.test(text);
}

export function professorLabel(row: Professor) {
  const name = row.name || "未命名导师";
  const school = row.school || "学校未填";
  const institute = row.institute ? ` / ${row.institute}` : "";
  return `${name} - ${school}${institute}`;
}

export function formFromProfessor(row: Professor): WriterFormState {
  return {
    professor_id: row.id,
    name: row.name ?? "",
    email: row.email ?? "",
    school: row.school ?? "",
    institute: row.institute ?? "",
    title: row.title ?? "",
    profile_url: row.profile_url ?? "",
    research_summary: row.research_summary ?? "",
    professor_intro: "",
    notes: row.notes ?? "",
  };
}

export function professorUpdatedAt(row: Professor) {
  const value = Date.parse(row.updated_at || row.created_at || "");
  return Number.isNaN(value) ? 0 : value;
}

export function matchProfessor(row: Professor, term: string) {
  if (!term) return true;
  return [row.name, row.email, row.school, row.institute, row.research_summary, row.matched_topics, row.fit_label, row.contact_stage, row.notes, row.next_action]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(term);
}

export function hasEnoughForWriting(row: Professor) {
  return Boolean((row.name || "").trim() && (row.school || "").trim() && (row.research_summary || "").trim());
}

export type CompletenessItem = {
  key: keyof WriterFormState;
  label: string;
  required: boolean;
  filled: boolean;
};

export function writerFormCompleteness(form: WriterFormState) {
  const items: CompletenessItem[] = [
    { key: "name", label: "姓名", required: true, filled: Boolean(form.name.trim()) },
    { key: "school", label: "学校", required: true, filled: Boolean(form.school.trim()) },
    { key: "research_summary", label: "方向", required: false, filled: Boolean(form.research_summary.trim()) },
    { key: "profile_url", label: "主页", required: false, filled: Boolean(form.profile_url.trim()) },
    { key: "email", label: "邮箱", required: false, filled: Boolean(form.email.trim()) },
  ];
  const filled = items.filter((item) => item.filled).length;
  const requiredFilled = items.filter((item) => item.required && item.filled).length;
  const requiredTotal = items.filter((item) => item.required).length;
  return {
    items,
    filled,
    total: items.length,
    requiredFilled,
    requiredTotal,
    percent: Math.round((filled / items.length) * 100),
    ready: requiredFilled === requiredTotal,
  };
}

export function professorCompleteness(row: Professor) {
  return writerFormCompleteness(formFromProfessor(row));
}
