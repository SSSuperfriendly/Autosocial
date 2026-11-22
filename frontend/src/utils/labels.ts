import type { SystemStatus } from "../types";

export type BadgeTone = "neutral" | "good" | "warn" | "danger";

export const BACKEND_META: Record<
  string,
  { label: string; shortLabel: string; description: string }
> = {
  "bigmodel-search": {
    label: "智谱联网搜索",
    shortLabel: "智谱",
    description: "更适合中文站点和国内高校官网。"
  },
  hybrid: {
    label: "混合模式",
    shortLabel: "混合",
    description: "把官网跟链和联网搜索一起用，适合作为默认方案。"
  },
  directory: {
    label: "官网目录抓取",
    shortLabel: "目录",
    description: "只沿学校官网目录和师资页抓取，最稳但覆盖更保守。"
  },
  ddg: {
    label: "DuckDuckGo",
    shortLabel: "DDG",
    description: "通用搜索兜底。"
  },
  "openai-search": {
    label: "OpenAI 搜索",
    shortLabel: "OpenAI",
    description: "适合补召回和跨站搜索。"
  }
};

const STAGE_META: Record<string, { label: string; tone: BadgeTone }> = {
  new: { label: "新发现", tone: "neutral" },
  reviewing: { label: "待复核", tone: "warn" },
  shortlisted: { label: "已心仪", tone: "good" },
  draft_ready: { label: "草稿待改", tone: "warn" },
  ready_to_send: { label: "可发送", tone: "good" },
  sent_waiting: { label: "已发送", tone: "warn" },
  replied: { label: "已回复", tone: "good" },
  in_conversation: { label: "沟通中", tone: "good" },
  rejected: { label: "已拒绝", tone: "danger" }
};

const VERIFICATION_META: Record<string, { label: string; tone: BadgeTone }> = {
  needs_review: { label: "待核验", tone: "warn" },
  verified: { label: "已核验", tone: "good" },
  rejected: { label: "已排除", tone: "danger" }
};

export const CONTACT_STAGE_OPTIONS = Object.entries(STAGE_META).map(([value, meta]) => ({
  value,
  label: meta.label,
}));

export const VERIFICATION_OPTIONS = Object.entries(VERIFICATION_META).map(([value, meta]) => ({
  value,
  label: meta.label,
}));

type FitCode = "high" | "medium" | "review" | "low" | "unknown";

function includesAny(value: string, candidates: string[]) {
  return candidates.some((candidate) => value.includes(candidate));
}

function detectFitCode(raw: string | null | undefined): FitCode {
  const value = String(raw ?? "").trim().toLowerCase();
  if (!value) return "unknown";
  if (includesAny(value, ["高匹配", "高", "high"])) return "high";
  if (includesAny(value, ["中匹配", "中", "medium", "mid"])) return "medium";
  if (includesAny(value, ["待复核", "待审核", "review"])) return "review";
  if (includesAny(value, ["低匹配", "低", "low"])) return "low";
  return "unknown";
}

export function backendLabel(key: string) {
  return BACKEND_META[key]?.label ?? key;
}

export function backendDescription(key: string) {
  return BACKEND_META[key]?.description ?? "当前后端已接入。";
}

export function contactStageLabel(stage: string) {
  return STAGE_META[stage]?.label ?? stage;
}

export function contactStageTone(stage: string): BadgeTone {
  return STAGE_META[stage]?.tone ?? "neutral";
}

export function verificationLabel(status: string) {
  return VERIFICATION_META[status]?.label ?? status;
}

export function verificationTone(status: string): BadgeTone {
  return VERIFICATION_META[status]?.tone ?? "neutral";
}

export function fitLabelText(label: string | null | undefined) {
  const code = detectFitCode(label);
  if (code === "high") return "高匹配";
  if (code === "medium") return "中匹配";
  if (code === "review") return "待复核";
  if (code === "low") return "低匹配";
  return String(label ?? "待评估");
}

export function fitTone(label: string | null | undefined): BadgeTone {
  const code = detectFitCode(label);
  if (code === "high") return "good";
  if (code === "medium" || code === "review") return "warn";
  if (code === "low") return "danger";
  return "neutral";
}

export function systemItemMeta(key: keyof SystemStatus) {
  const mapping: Record<keyof SystemStatus, string> = {
    llm: "大模型",
    bigmodel_search: "智谱搜索",
    openai_search: "OpenAI 搜索",
    directory_crawl: "官网目录抓取",
    ddg: "DuckDuckGo",
    smtp: "SMTP 发信",
    imap: "IMAP 收信"
  };
  return mapping[key];
}

export function discoveryStageLabel(stage: string | undefined) {
  const mapping: Record<string, string> = {
    prepare: "准备中",
    search: "联网检索",
    dedupe: "结果去重",
    extract: "抽取入池",
    done: "完成"
  };
  return mapping[String(stage ?? "")] ?? String(stage ?? "处理中");
}

export function formatDate(value?: string | null) {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function formatDateShort(value?: string | null) {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("zh-CN");
}
