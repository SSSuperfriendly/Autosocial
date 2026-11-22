import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import type { SystemStatus, TargetSchoolRow } from "../types";
import { buildStudentProfileMarkdown, parseStudentProfile, type StudentProfileForm } from "../utils/studentProfile";
import { linesToText, textToLines } from "../utils/text";

type Props = {
  targetRows: TargetSchoolRow[];
  studentProfile: string;
  emailTemplate: string;
  onSaved: () => void | Promise<void>;
  systemStatus: SystemStatus | null;
};

type ProfileSectionKey =
  | "basic"
  | "interests"
  | "experience"
  | "thinking"
  | "communication"
  | "template";

const TEMPLATE_PLACEHOLDERS = [
  "{{professor_salutation}}",
  "{{student_name}}",
  "{{student_school}}",
  "{{student_major_grade}}",
  "{{promotion_status_sentence}}",
  "{{student_summary_paragraph}}",
  "{{professor_thinking_paragraph}}",
  "{{reply_request_sentence}}",
  "{{student_homepage}}",
  "{{student_contact}}",
  "{{student_rank_label}}",
  "{{topic_hint}}",
  "{{target_year_full}}",
  "{{target_year_short}}",
  "{{current_date_cn}}",
];

const PROFILE_SECTION_LABELS: Record<ProfileSectionKey, string> = {
  basic: "基础信息",
  interests: "研究兴趣",
  experience: "学业与经历",
  thinking: "思考素材",
  communication: "沟通目标与风格",
  template: "邮件模板",
};

function emptyProfile(): StudentProfileForm {
  return {
    name: "",
    school: "",
    major: "",
    grade: "",
    contact: "",
    homepage: "",
    researchIntro: "",
    interests: [],
    gpa: "",
    ranking: "",
    promotionStatus: "",
    researchExperience: "",
    awards: [],
    thinkingMaterials: [],
    communicationGoal: "",
    styleRules: [],
  };
}

function shortText(value: string, max = 28) {
  const text = value.trim().replace(/\s+/g, " ");
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function profileSectionSummary(key: ProfileSectionKey, form: StudentProfileForm, emailTemplate: string) {
  if (key === "basic") {
    const summary = [form.name, form.school, form.major].filter(Boolean).join(" / ");
    return summary || "姓名、学校、联系方式";
  }
  if (key === "interests") {
    if (form.interests.length) {
      return `${form.interests.slice(0, 2).join(" / ")}${form.interests.length > 2 ? ` 等 ${form.interests.length} 项` : ""}`;
    }
    return shortText(form.researchIntro) || "方向偏好";
  }
  if (key === "experience") {
    const summary = [form.gpa && `GPA ${form.gpa}`, form.ranking && `排名 ${form.ranking}`].filter(Boolean).join(" / ");
    if (summary) return summary;
    if (form.researchExperience.trim()) return shortText(form.researchExperience);
    return "GPA、排名、科研经历";
  }
  if (key === "thinking") {
    if (form.thinkingMaterials.length) {
      return `${form.thinkingMaterials.slice(0, 1).join("")}${form.thinkingMaterials.length > 1 ? ` +${form.thinkingMaterials.length - 1}` : ""}`;
    }
    return "课程基础与思考线索";
  }
  if (key === "communication") {
    if (form.communicationGoal.trim()) return shortText(form.communicationGoal);
    if (form.styleRules.length) return `${form.styleRules.length} 条风格要求`;
    return "沟通目标与写作风格";
  }
  return emailTemplate.trim() ? `${TEMPLATE_PLACEHOLDERS.length} 个占位符已接入` : "编辑邮件模板";
}

export function SettingsPage({ targetRows, studentProfile, emailTemplate, systemStatus, onSaved }: Props) {
  const [profileForm, setProfileForm] = useState<StudentProfileForm>(emptyProfile);
  const [localEmailTemplate, setLocalEmailTemplate] = useState(emailTemplate);
  const [targets, setTargets] = useState<TargetSchoolRow[]>(targetRows);
  const [expandedProfileSection, setExpandedProfileSection] = useState<ProfileSectionKey>("basic");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [savingAll, setSavingAll] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);

  useEffect(() => setLocalEmailTemplate(emailTemplate), [emailTemplate]);
  useEffect(() => setTargets(targetRows), [targetRows]);
  useEffect(() => {
    setProfileForm(studentProfile.trim() ? parseStudentProfile(studentProfile) : emptyProfile());
  }, [studentProfile]);

  const builtStudentProfile = useMemo(() => buildStudentProfileMarkdown(profileForm), [profileForm]);
  const interestLines = useMemo(() => linesToText(profileForm.interests), [profileForm.interests]);
  const awardLines = useMemo(() => linesToText(profileForm.awards), [profileForm.awards]);
  const thinkingMaterialLines = useMemo(() => linesToText(profileForm.thinkingMaterials), [profileForm.thinkingMaterials]);
  const styleRuleLines = useMemo(() => linesToText(profileForm.styleRules), [profileForm.styleRules]);

  const profileDirty = builtStudentProfile !== studentProfile || localEmailTemplate !== emailTemplate;
  const targetsDirty = useMemo(() => JSON.stringify(targets) !== JSON.stringify(targetRows), [targets, targetRows]);
  const dirty = profileDirty || targetsDirty;
  const filledProfileSections = useMemo(
    () =>
      (
        [
          !![profileForm.name, profileForm.school, profileForm.major, profileForm.contact].filter(Boolean).length,
          !!profileForm.interests.length || !!profileForm.researchIntro.trim(),
          !!profileForm.researchExperience.trim() || !!profileForm.gpa.trim() || !!profileForm.ranking.trim(),
          !!profileForm.thinkingMaterials.length,
          !!profileForm.communicationGoal.trim() || !!profileForm.styleRules.length,
          !!localEmailTemplate.trim(),
        ] as boolean[]
      ).filter(Boolean).length,
    [localEmailTemplate, profileForm],
  );

  function patchProfile(patch: Partial<StudentProfileForm>) {
    setProfileForm((current) => ({ ...current, ...patch }));
  }

  async function handleSaveAll() {
    setSavingAll(true);
    setMessage("");
    setError("");
    try {
      await api.saveStudentProfile(builtStudentProfile);
      await api.saveEmailTemplate(localEmailTemplate);
      await api.saveTargets(targets);
      setMessage("设置已保存。");
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存设置失败。");
    } finally {
      setSavingAll(false);
    }
  }

  async function handleSaveProfile() {
    setSavingProfile(true);
    setMessage("");
    setError("");
    try {
      await api.saveStudentProfile(builtStudentProfile);
      await api.saveEmailTemplate(localEmailTemplate);
      setMessage("学生画像、思考素材和邮件模板已保存。");
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存学生画像失败。");
    } finally {
      setSavingProfile(false);
    }
  }

  function renderProfileCard(
    key: ProfileSectionKey,
    body: React.ReactNode,
  ) {
    const expanded = expandedProfileSection === key;
    return (
      <article className={`settings-editor-card settings-editor-card-compact ${expanded ? "expanded" : "collapsed"}`}>
        <button className="settings-collapse-trigger" onClick={() => setExpandedProfileSection(key)} type="button">
          <div>
            <strong>{PROFILE_SECTION_LABELS[key]}</strong>
            <p className="settings-target-summary">{profileSectionSummary(key, profileForm, localEmailTemplate)}</p>
          </div>
          <span className={expanded ? "smart-chip dark-chip" : "smart-chip muted"}>{expanded ? "当前" : "编辑"}</span>
        </button>
        {expanded ? <div className="settings-collapsible-body">{body}</div> : null}
      </article>
    );
  }

  return (
    <div className="page-stack page-stack-tight">
      <SectionCard
        title="设置"
        actions={
          <button className="primary-button" onClick={handleSaveAll} disabled={!dirty || savingAll} type="button">
            {savingAll ? "保存中..." : "保存设置"}
          </button>
        }
      >
        <div className="chip-row">
          <span className={dirty ? "smart-chip warning" : "smart-chip muted"}>{dirty ? "有未保存修改" : "已同步"}</span>
          <span className="smart-chip tertiary">画像 {filledProfileSections}/6</span>
        </div>
        {message ? <div className="success-box">{message}</div> : null}
        {error ? <div className="error-box">{error}</div> : null}
      </SectionCard>

      <SectionCard
        title="学生画像"
        actions={
          <button className="ghost-button" onClick={handleSaveProfile} disabled={!profileDirty || savingProfile} type="button">
            {savingProfile ? "保存中..." : "保存画像与模板"}
          </button>
        }
      >
        <div className="settings-card-list settings-card-list-simple">
          {renderProfileCard(
            "basic",
            <div className="form-grid form-grid-simple">
              <label>
                姓名
                <input value={profileForm.name} onChange={(event) => patchProfile({ name: event.target.value })} />
              </label>
              <label>
                学校
                <input value={profileForm.school} onChange={(event) => patchProfile({ school: event.target.value })} />
              </label>
              <label>
                专业
                <input value={profileForm.major} onChange={(event) => patchProfile({ major: event.target.value })} />
              </label>
              <label>
                年级
                <input value={profileForm.grade} onChange={(event) => patchProfile({ grade: event.target.value })} />
              </label>
              <label>
                联系方式
                <input value={profileForm.contact} onChange={(event) => patchProfile({ contact: event.target.value })} />
              </label>
              <label>
                个人主页
                <input value={profileForm.homepage} onChange={(event) => patchProfile({ homepage: event.target.value })} />
              </label>
            </div>,
          )}

          {renderProfileCard(
            "interests",
            <div className="split-grid split-grid-simple">
              <label>
                开场描述
                <textarea value={profileForm.researchIntro} onChange={(event) => patchProfile({ researchIntro: event.target.value })} />
              </label>
              <label>
                兴趣方向
                <textarea
                  value={interestLines}
                  onChange={(event) => patchProfile({ interests: textToLines(event.target.value) })}
                  placeholder="每行一个方向"
                />
              </label>
            </div>,
          )}

          {renderProfileCard(
            "experience",
            <>
              <div className="form-grid form-grid-simple">
                <label>
                  GPA
                  <input value={profileForm.gpa} onChange={(event) => patchProfile({ gpa: event.target.value })} />
                </label>
                <label>
                  排名
                  <input value={profileForm.ranking} onChange={(event) => patchProfile({ ranking: event.target.value })} />
                </label>
                <label>
                  申请状态 / 目标学位
                  <input value={profileForm.promotionStatus} onChange={(event) => patchProfile({ promotionStatus: event.target.value })} placeholder="填写申请学位、计划入学年份或当前进展" />
                </label>
              </div>
              <div className="split-grid split-grid-simple">
                <label>
                  科研与项目经历
                  <textarea
                    className="large-textarea"
                    value={profileForm.researchExperience}
                    onChange={(event) => patchProfile({ researchExperience: event.target.value })}
                  />
                </label>
                <label>
                  奖项与竞赛
                  <textarea
                    className="large-textarea"
                    value={awardLines}
                    onChange={(event) => patchProfile({ awards: textToLines(event.target.value) })}
                    placeholder="每行一条"
                  />
                </label>
              </div>
            </>,
          )}

          {renderProfileCard(
            "thinking",
            <label>
              可复用课程基础 / 思考线索
              <textarea
                value={thinkingMaterialLines}
                onChange={(event) => patchProfile({ thinkingMaterials: textToLines(event.target.value) })}
                placeholder="每行一条"
              />
            </label>,
          )}

          {renderProfileCard(
            "communication",
            <div className="split-grid split-grid-simple">
              <label>
                沟通目标
                <textarea value={profileForm.communicationGoal} onChange={(event) => patchProfile({ communicationGoal: event.target.value })} />
              </label>
              <label>
                风格要求
                <textarea
                  value={styleRuleLines}
                  onChange={(event) => patchProfile({ styleRules: textToLines(event.target.value) })}
                  placeholder="每行一条"
                />
              </label>
            </div>,
          )}

          {renderProfileCard(
            "template",
            <>
              <div className="settings-template-meta">
                {TEMPLATE_PLACEHOLDERS.map((item) => (
                  <span className="smart-chip secondary" key={item}>
                    {item}
                  </span>
                ))}
              </div>
              <label>
                模板内容
                <textarea
                  className="large-textarea settings-template-area"
                  value={localEmailTemplate}
                  onChange={(event) => setLocalEmailTemplate(event.target.value)}
                />
              </label>
            </>,
          )}
        </div>
      </SectionCard>

      <SectionCard title="目标学校" actions={<button className="ghost-button" type="button" onClick={() => setTargets((current) => [...current, { school: "", domains: "", entry_urls: "" }])}>添加学校</button>}>
        <p className="subtle-note">添加后可在“发现导师”中选择。请填写学校官网域名与师资入口，以便检索和核验。</p>
        {targets.length ? targets.map((row, index) => <div className="settings-target-row" key={index}>
          <label>学校名称<input value={row.school} onChange={(event) => setTargets((current) => current.map((item, i) => i === index ? { ...item, school: event.target.value } : item))} placeholder="学校名称" /></label>
          <label>官网域名<input value={row.domains || ""} onChange={(event) => setTargets((current) => current.map((item, i) => i === index ? { ...item, domains: event.target.value } : item))} placeholder="例如：example.edu" /></label>
          <button className="ghost-button small-button danger-button" type="button" onClick={() => setTargets((current) => current.filter((_, i) => i !== index))}>移除</button>
          <label>学院（可选）<input value={row.institute || ""} onChange={(event) => setTargets((current) => current.map((item, i) => i === index ? { ...item, institute: event.target.value } : item))} /></label>
          <label>师资入口网址<input value={row.entry_urls || ""} onChange={(event) => setTargets((current) => current.map((item, i) => i === index ? { ...item, entry_urls: event.target.value } : item))} placeholder="https://…" /></label>
        </div>) : <div className="empty-state">尚未配置目标学校。手动管理导师无需添加学校配置。</div>}
        <div className="inline-actions" style={{ marginTop: 16 }}><button className="primary-button" type="button" disabled={!targetsDirty || savingAll} onClick={handleSaveAll}>{savingAll ? "保存中…" : "保存目标学校"}</button></div>
      </SectionCard>

      <SectionCard title="可选能力">
        <p className="subtle-note">导师管理、沟通记录与跟进计划无需 API Key。智能检索与写信可按需要配置环境变量，重启服务后生效。</p>
        <div className="chip-row"><span className="smart-chip muted">邮件生成 · {systemStatus?.llm.configured ? "已配置" : "使用内置模板"}</span><span className="smart-chip muted">智谱搜索 · {systemStatus?.bigmodel_search.configured ? "已配置" : "未配置"}</span><span className="smart-chip muted">OpenAI 搜索 · {systemStatus?.openai_search.configured ? "已配置" : "未配置"}</span><span className="smart-chip muted">SMTP / IMAP · 可选</span></div>
      </SectionCard>

    </div>
  );
}
