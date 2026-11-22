export type StudentProfileForm = {
  name: string;
  school: string;
  major: string;
  grade: string;
  contact: string;
  homepage: string;
  researchIntro: string;
  interests: string[];
  gpa: string;
  ranking: string;
  promotionStatus: string;
  researchExperience: string;
  awards: string[];
  thinkingMaterials: string[];
  communicationGoal: string;
  styleRules: string[];
};

const DEFAULT_RESEARCH_INTRO = "";
const DEFAULT_PROMOTION_STATUS = "";

function normalizeLine(line: string) {
  return line.trim();
}

function splitSections(content: string) {
  const sections: Record<string, string[]> = {};
  let current = "";

  for (const rawLine of content.split(/\r?\n/)) {
    const line = normalizeLine(rawLine);
    if (!line) continue;
    if (line.startsWith("#")) {
      current = line.replace(/^#+\s*/, "").trim();
      sections[current] = sections[current] ?? [];
      continue;
    }
    if (!current) continue;
    sections[current] = sections[current] ?? [];
    sections[current].push(line);
  }

  return sections;
}

function getFieldValue(lines: string[], field: string) {
  const prefix = `${field}：`;
  const match = lines.find((line) => line.startsWith(prefix));
  return match ? match.slice(prefix.length).trim() : "";
}

function getBulletLines(lines: string[]) {
  return lines
    .filter((line) => line.startsWith("-"))
    .map((line) => line.replace(/^-+\s*/, "").trim())
    .filter(Boolean);
}

function getPlainLines(lines: string[]) {
  return lines
    .filter((line) => !line.startsWith("-") && !line.includes("："))
    .map((line) => line.trim())
    .filter(Boolean);
}

export function parseStudentProfile(content: string): StudentProfileForm {
  const sections = splitSections(content);
  const basics = sections["个人简介"] ?? [];
  const research = sections["研究兴趣"] ?? [];
  const academics = sections["学业情况"] ?? [];
  const researchExperience = sections["科研与项目经历"] ?? sections["科研经历"] ?? sections["项目经历"] ?? [];
  const awards = sections["奖项与竞赛"] ?? sections["奖项"] ?? sections["竞赛"] ?? [];
  const thinkingMaterials = sections["思考素材"] ?? sections["相关课程与思考"] ?? sections["课程基础"] ?? [];
  const communicationGoal = sections["沟通目标"] ?? [];
  const styleRequirements = sections["风格要求"] ?? [];

  const researchPlain = getPlainLines(research);
  const academicBullets = getBulletLines(academics);
  const promotionStatus =
    getFieldValue(academicBullets, "申请状态") || (
    academicBullets.find((item) => item.includes("推免") || item.includes("保研")) ??
    getPlainLines(academics).find((item) => item.includes("推免") || item.includes("保研")) ??
    DEFAULT_PROMOTION_STATUS);

  return {
    name: getFieldValue(basics, "姓名"),
    school: getFieldValue(basics, "学校"),
    major: getFieldValue(basics, "专业"),
    grade: getFieldValue(basics, "年级"),
    contact: getFieldValue(basics, "联系方式"),
    homepage: getFieldValue(basics, "个人主页"),
    researchIntro: researchPlain[0] ?? DEFAULT_RESEARCH_INTRO,
    interests: getBulletLines(research),
    gpa:
      academicBullets.find((item) => item.startsWith("GPA："))?.replace(/^GPA：/, "").trim() ??
      getFieldValue(academics, "GPA"),
    ranking:
      academicBullets.find((item) => item.startsWith("排名："))?.replace(/^排名：/, "").trim() ??
      getFieldValue(academics, "排名"),
    promotionStatus,
    researchExperience: [...getPlainLines(researchExperience), ...getBulletLines(researchExperience)].join("\n"),
    awards: getBulletLines(awards).length ? getBulletLines(awards) : [...getPlainLines(awards)],
    thinkingMaterials: getBulletLines(thinkingMaterials).length
      ? getBulletLines(thinkingMaterials)
      : [...getPlainLines(thinkingMaterials)],
    communicationGoal: getPlainLines(communicationGoal).join("\n"),
    styleRules: getBulletLines(styleRequirements).length
      ? getBulletLines(styleRequirements)
      : [...getPlainLines(styleRequirements)],
  };
}

function pushSection(lines: string[], title: string, bodyLines: string[]) {
  lines.push(`# ${title}`);
  for (const line of bodyLines) {
    const normalized = line.trim();
    if (normalized) {
      lines.push(normalized);
    }
  }
  lines.push("");
}

export function buildStudentProfileMarkdown(form: StudentProfileForm) {
  const lines: string[] = [];

  pushSection(lines, "个人简介", [
    `姓名：${form.name.trim()}`,
    `学校：${form.school.trim()}`,
    `专业：${form.major.trim()}`,
    `年级：${form.grade.trim()}`,
    `联系方式：${form.contact.trim()}`,
    `个人主页：${form.homepage.trim()}`,
  ]);

  pushSection(lines, "研究兴趣", [
    form.researchIntro.trim() || DEFAULT_RESEARCH_INTRO,
    ...form.interests.map((item) => `- ${item.trim()}`),
  ]);

  pushSection(lines, "学业情况", [
    form.gpa.trim() ? `- GPA：${form.gpa.trim()}` : "",
    form.ranking.trim() ? `- 排名：${form.ranking.trim()}` : "",
    form.promotionStatus.trim() ? `- 申请状态：${form.promotionStatus.trim()}` : "",
  ]);

  pushSection(lines, "科研与项目经历", form.researchExperience.split(/\r?\n/));
  pushSection(lines, "奖项与竞赛", form.awards.map((item) => `- ${item.trim()}`));
  pushSection(lines, "思考素材", form.thinkingMaterials.map((item) => `- ${item.trim()}`));
  pushSection(lines, "沟通目标", form.communicationGoal.split(/\r?\n/));
  pushSection(lines, "风格要求", form.styleRules.map((item) => `- ${item.trim()}`));

  return lines.join("\n").trim();
}
