import { expect, test } from "vitest";
import { applyPatch } from "./patch";
import type { Page } from "./types";

const page: Page = {
  version: 1, company: { name: "X", okved: "", role: "", date: "" },
  widgets: [{ id: "a", column: "news", title: "A" }, { id: "b", column: "analytics", title: "B" }],
  links: [{ id: "l1", from: "a", to: "b" }],
};

test("add / update / remove, links follow removed widget", () => {
  const p = applyPatch(page, {
    base_version: 1, version: 2,
    ops: [
      { op: "add_widget", widget: { id: "c", column: "decisions", title: "C" } },
      { op: "add_link", link: { id: "l2", from: "b", to: "c" } },
      { op: "update_widget", id: "a", fields: { title: "A2", tags: { source: "human" } } },
      { op: "remove_widget", id: "b" },
    ],
  })!;
  expect(p.version).toBe(2);
  expect(p.widgets.map(w => w.title)).toEqual(["A2", "C"]);
  expect(p.links).toEqual([]);
  expect(p.widgets[0].tags).toEqual({ source: "human" });
});

test("stale base version is rejected", () => {
  expect(applyPatch(page, { base_version: 5, version: 6, ops: [] })).toBeNull();
});
