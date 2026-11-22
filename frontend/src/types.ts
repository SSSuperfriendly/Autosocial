export type SystemStatus = {
  llm: { configured: boolean; provider: string; model: string };
  bigmodel_search: { configured: boolean; enabled_by_preference: boolean; model: string };
  openai_search: { configured: boolean; enabled_by_preference: boolean; model: string };
  directory_crawl: { configured: boolean; enabled_by_preference: boolean; model: string };
  ddg: { configured: boolean; enabled_by_preference: boolean; model: string };
  smtp: {
    configured: boolean;
    healthy: boolean;
    message: string;
    sender: string;
    test_recipient_enabled?: boolean;
    test_recipient_mode?: string;
    test_recipient_email?: string;
  };
  imap: { configured: boolean; healthy: boolean; message: string; folder: string };
};

export type Metrics = {
  professors_total: number;
  shortlisted_total: number;
  verified_total: number;
  drafts_total: number;
  approved_total: number;
  sent_total: number;
  replies_total: number;
  school_breakdown: Array<{ school: string; count: number }>;
  stage_breakdown: Array<{ contact_stage: string; count: number }>;
  fit_breakdown: Array<{ fit_label: string; count: number }>;
};

export type Preferences = {
  research: {
    primary_focus: string;
    preferred_topics: string[];
    acceptable_topics: string[];
    excluded_topics: string[];
    free_text_notes: string;
  };
  discovery: {
    preferred_backend: string;
    allow_bigmodel_search: boolean;
    allow_openai_search: boolean;
    allow_directory_crawl: boolean;
    allow_ddg: boolean;
    allow_hybrid: boolean;
    limit_per_school: number;
    max_crawl_pages: number;
    max_crawl_depth: number;
    min_match_score: number;
  };
  workflow: {
    default_contact_stage: string;
    auto_shortlist_after_verify: boolean;
  };
};

export type TargetSchoolRow = {
  school: string;
  institute?: string;
  domains?: string;
  entry_urls?: string;
  search_hint?: string;
};

export type DiscoveryPromptRow = {
  id: string;
  name: string;
  enabled: boolean;
  content: string;
};

export type Professor = {
  id: number;
  school: string;
  institute?: string | null;
  name?: string | null;
  email?: string | null;
  title?: string | null;
  profile_url: string;
  source_domain?: string | null;
  research_summary?: string | null;
  matched_topics: string;
  verification_status: string;
  shortlisted: boolean;
  fit_score: number;
  fit_label: string;
  fit_reason?: string | null;
  contact_stage: string;
  publication_signal?: string | null;
  scholar_url?: string | null;
  last_contacted_at?: string | null;
  last_replied_at?: string | null;
  notes?: string | null;
  note_priority_score?: number | null;
  note_priority_reason?: string | null;
  note_priority_source?: string | null;
  interaction_priority_score?: number | null;
  interaction_priority_reason?: string | null;
  trashed_at?: string | null;
  created_at?: string | null;
  draft_status?: string | null;
  updated_at?: string | null;
  next_follow_up?: string | null;
  next_action?: string | null;
};

export type ContactEvent = {
  id: number;
  professor_id: number;
  kind: "note" | "email_sent" | "reply" | "meeting";
  content: string;
  occurred_at: string;
  created_at: string;
  professor_name?: string | null;
  school?: string | null;
};

export type Draft = {
  draft_id: number;
  professor_id: number;
  school: string;
  name?: string | null;
  email?: string | null;
  subject: string;
  body: string;
  approval_status: string;
  generator?: string | null;
  generation_notes?: string | null;
  fit_score: number;
  contact_stage: string;
  shortlisted: boolean;
};

export type Reply = {
  id: number;
  school: string;
  name?: string | null;
  email?: string | null;
  contact_stage: string;
  from_email: string;
  subject?: string | null;
  body_preview?: string | null;
  received_at?: string | null;
  created_at?: string | null;
};

export type DiscoveryResult = {
  backend: string;
  discovered_count: number;
  ingested_count: number;
  discovered_rows: Array<Record<string, string>>;
  ingest_failures: Array<Record<string, string>>;
  filtered_out: Array<Record<string, string | number | null>>;
  review_required_rows: Array<Record<string, string | number | null>>;
  not_ingested_rows: Array<Record<string, string | number | null>>;
  progress_events: Array<Record<string, unknown>>;
  research_profile_summary: string;
};
