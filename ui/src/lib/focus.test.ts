import { expect, test } from "vitest";
import type { Page } from "../api";
import { computeFocus } from "./focus";

const page: Page = {
  version: 1, company: { name: "c", okved: "", role: "r", date: "d" },
  widgets: ["n1", "n2", "a1", "d1"].map(id => ({ id, column: id[0] === "n" ? "news" : id[0] === "a" ? "analytics" : "decisions", title: id })),
  links: [{ id: "l1", from: "n1", to: "a1" }, { id: "l2", from: "a1", to: "d1" }],
};

test("nothing open: overview, nothing hidden", () => {
  const f = computeFocus(page, new Set(), null);
  expect(f.selected).toEqual([]); expect(f.hidden.size).toBe(0);
});

test("open analytics keeps its whole chain and hides the unrelated news", () => {
  const f = computeFocus(page, new Set(["a1"]), null);
  expect([...f.hidden]).toEqual(["n2"]);
  expect(f.visibleLinks.map(l => l.id)).toEqual(["l1", "l2"]);
});

test("hovering a widget highlights it and its links", () => {
  const f = computeFocus(page, new Set(), { type: "widget", id: "a1" });
  expect([...f.hlLinks].sort()).toEqual(["l1", "l2"]); expect(f.hlWidgets.has("a1")).toBe(true);
});
