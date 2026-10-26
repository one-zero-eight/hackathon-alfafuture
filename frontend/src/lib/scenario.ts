import type { Page, Patch, Scenario, ScenarioKind } from "../api";

export const SCENARIO_LABEL: Record<ScenarioKind, string> = {
  question: "Вопрос", extend: "Дополнение темы", perspective: "Новая перспектива",
  edit: "Правка вывода", remove: "Удаление", link: "Новая ссылка", proposal: "Предложение по компании",
};

export interface Change { kind: "added" | "replaced" | "removed"; title: string }

// The server's scenario wins; otherwise guess from the ops (a heuristic, shown as such by the caller)
export function recognize(patch: Patch | null, server?: Scenario): { scenario: Scenario; inferred: boolean } {
  if (server) return { scenario: server, inferred: false };
  if (!patch || !patch.ops.length) return { scenario: { kind: "question" }, inferred: true };
  const removed = patch.ops.filter(o => o.op === "remove_widget").length;
  const added = patch.ops.filter(o => o.op === "add_widget").length;
  const kind: ScenarioKind = added && removed >= 3 ? "perspective" : added ? "extend" : removed ? "remove" : "edit";
  return { scenario: { kind }, inferred: true };
}

// What a patch does to the page, in the user's words (titles are taken from the page before the patch)
export function summarize(before: Page, patch: Patch): Change[] {
  const title = (id: string) => before.widgets.find(w => w.id === id)?.title ?? id;
  const out: Change[] = [];
  for (const o of patch.ops) {
    if (o.op === "add_widget") out.push({ kind: "added", title: o.widget.title });
    else if (o.op === "update_widget") out.push({ kind: "replaced", title: o.fields?.title ?? title(o.id) });
    else if (o.op === "remove_widget") out.push({ kind: "removed", title: title(o.id) });
  }
  return out;
}
