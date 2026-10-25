import { describe, expect, it } from "vitest";
import { steps } from "./stages";

const state = (s: Parameters<typeof steps>[0]) => steps(s).map(x => x.state);

describe("steps", () => {
  it("queued profile waits at the first step", () => {
    expect(state({ status: "queued" })).toEqual(["active", "todo", "todo"]);
  });
  it("moves along the stage and puts the counts into the labels", () => {
    const rank = steps({ status: "running", stage: "rank", found: 40 });
    expect(rank.map(x => x.state)).toEqual(["done", "active", "todo"]);
    expect(rank[1].label).toBe("Найдено 40 новостей, выбор актуального");
    const analysis = steps({ status: "running", stage: "analysis", found: 40, selected: 10 });
    expect(analysis[2]).toEqual({ label: "ИИ анализирует 10 новостей, данные компании и аналитические статьи от АльфаБанк", state: "active" });
  });
  it("everything is done when the page is ready", () => {
    expect(state({ status: "ready" })).toEqual(["done", "done", "done"]);
  });
});
