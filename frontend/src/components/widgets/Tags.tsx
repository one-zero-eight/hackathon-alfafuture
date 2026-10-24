import type { Tags as TagsData } from "../../api";

// kind -> [value -> label]; labels are Russian, API values are English (docs/backend.md)
const LABELS = {
  confidence: { title: "Уверенность", values: { reliable: "достоверно", probable: "вероятно", possible: "возможно" } },
  source: { title: "Источник анализа", values: { ai: "ИИ", alfa: "Альфа", human: "человек" } },
  urgency: { title: "Срочность", values: { urgent: "срочно", medium_term: "среднесрочно", not_urgent: "не срочно" } },
} as const;

export function Tags({ tags }: { tags?: TagsData }) {
  if (!tags) return null;
  const chip = (kind: string, title: string, value: string, text: string) =>
    <span key={kind} className={`tag tag-${kind}-${value}`} title={title}>{text}</span>;
  return (
    <div className="tags">
      {tags.industry && chip("industry", "Отрасль", "x", tags.industry)}
      {tags.confidence && chip("confidence", LABELS.confidence.title, tags.confidence, LABELS.confidence.values[tags.confidence])}
      {tags.source && chip("source", LABELS.source.title, tags.source, LABELS.source.values[tags.source])}
      {tags.urgency && chip("urgency", LABELS.urgency.title, tags.urgency, LABELS.urgency.values[tags.urgency])}
    </div>
  );
}
