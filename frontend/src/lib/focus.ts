import type { LinkSkeleton, Page } from "../api";

export type Hover = { type: "widget" | "link"; id: string } | null;

export interface Focus {
  hlLinks: Set<string>; hlWidgets: Set<string>; // highlighted by hover
  selected: string[]; hidden: Set<string>;       // opened widgets; everything not chained to them
  visibleLinks: LinkSkeleton[];
}

// Focus mode: with widgets selected, show them plus everything chained to at least one of them
// (upstream and downstream along the links); with nothing selected the page is the one-section overview.
export function computeFocus(page: Page, open: Set<string>, hover: Hover): Focus {
  const hlLinks = new Set<string>(), hlWidgets = new Set<string>();
  if (hover?.type === "link") {
    const l = page.links.find(x => x.id === hover.id);
    if (l) { hlLinks.add(l.id); hlWidgets.add(l.from).add(l.to); }
  } else if (hover) {
    hlWidgets.add(hover.id);
    page.links.filter(l => l.from === hover.id || l.to === hover.id).forEach(l => hlLinks.add(l.id));
  }
  const selected = page.widgets.filter(w => open.has(w.id)).map(w => w.id);
  const hidden = new Set<string>();
  if (selected.length) {
    const keep = new Set(selected);
    const walk = (start: string, a: "from" | "to", b: "from" | "to") => {
      const seen = new Set([start]), stack = [start];
      while (stack.length) {
        const x = stack.pop()!;
        for (const l of page.links) if (l[a] === x && !seen.has(l[b])) { seen.add(l[b]); keep.add(l[b]); stack.push(l[b]); }
      }
    };
    selected.forEach(id => { walk(id, "to", "from"); walk(id, "from", "to"); });
    page.widgets.forEach(w => { if (!keep.has(w.id)) hidden.add(w.id); });
    // An analytics card is about the whole set of news, so the news column stays complete.
    if (selected.some(id => page.widgets.find(w => w.id === id)?.column === "analytics")) {
      page.widgets.forEach(w => { if (w.column === "news") hidden.delete(w.id); });
    }
  }
  return { hlLinks, hlWidgets, selected, hidden, visibleLinks: page.links.filter(l => !hidden.has(l.from) && !hidden.has(l.to)) };
}
