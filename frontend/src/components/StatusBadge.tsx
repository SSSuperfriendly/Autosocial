type Props = {
  text: string;
  tone?: "neutral" | "good" | "warn" | "danger";
};

export function StatusBadge({ text, tone = "neutral" }: Props) {
  return <span className={`status-badge ${tone}`}>{text}</span>;
}
