import type { ProfileStatus } from "../api";

export interface Step { label: string; state: "done" | "active" | "todo" }

const ORDER = ["search", "rank", "analysis"];

// The three steps of building a page for the vertical timeline; counts appear in a label once the server knows them.
export function steps(s: Pick<ProfileStatus, "status" | "stage" | "found" | "selected">): Step[] {
  const at = s.status === "ready" ? ORDER.length : s.status === "running" && s.stage ? ORDER.indexOf(s.stage) : 0;
  const labels = [
    "Поиск новостей",
    s.found != null ? `Найдено ${s.found} новостей, выбор актуального` : "Выбор актуальных новостей",
    `ИИ анализирует ${s.selected != null ? s.selected + " новостей, " : ""}данные компании и аналитические статьи от АльфаБанк`,
  ];
  return labels.map((label, i) => ({ label, state: i < at ? "done" : i === at ? "active" : "todo" }));
}
