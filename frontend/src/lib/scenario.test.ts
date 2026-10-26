import { expect, test } from "vitest";
import { recognize, summarize } from "./scenario";
import type { Page } from "../api";

const page: Page = {
  version: 1, company: { name: "X", okved: "", role: "", date: "" },
  widgets: [{ id: "a", column: "news", title: "A" }, { id: "b", column: "analytics", title: "B" }], links: [],
};

test("no patch is a question; server scenario wins", () => {
  expect(recognize(null)).toEqual({ scenario: { kind: "question" }, inferred: true });
  expect(recognize(null, { kind: "link" }).inferred).toBe(false);
});

test("kind is inferred from ops", () => {
  const p = (...ops: any[]) => ({ base_version: 1, version: 2, ops });
  expect(recognize(p({ op: "remove_widget", id: "a" })).scenario.kind).toBe("remove");
  expect(recognize(p({ op: "add_widget", widget: { id: "c", column: "news", title: "C" } })).scenario.kind).toBe("extend");
  expect(recognize(p({ op: "update_widget", id: "a" })).scenario.kind).toBe("edit");
});

test("summary names added, replaced and removed blocks", () => {
  const s = summarize(page, { base_version: 1, version: 2, ops: [
    { op: "add_widget", widget: { id: "c", column: "news", title: "C" } },
    { op: "update_widget", id: "a", fields: { title: "A2" } },
    { op: "remove_widget", id: "b" },
    { op: "add_link", link: { id: "l", from: "a", to: "c" } },
  ] });
  expect(s).toEqual([{ kind: "added", title: "C" }, { kind: "replaced", title: "A2" }, { kind: "removed", title: "B" }]);
});
