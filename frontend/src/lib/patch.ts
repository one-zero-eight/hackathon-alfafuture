import type { Page, Patch } from "../api";

// Applies a server patch to the page skeleton. Returns null when the patch does not
// continue the current version: the caller must then reload /page.
export function applyPatch(page: Page, patch: Patch): Page | null {
  if (patch.base_version !== page.version) return null;
  let widgets = page.widgets, links = page.links;
  for (const o of patch.ops) {
    switch (o.op) {
      case "add_widget": widgets = [...widgets, o.widget]; break;
      case "update_widget": widgets = widgets.map(w => (w.id === o.id ? { ...w, ...o.fields } : w)); break;
      case "remove_widget":
        widgets = widgets.filter(w => w.id !== o.id);
        links = links.filter(l => l.from !== o.id && l.to !== o.id); // links never dangle
        break;
      case "add_link": links = [...links, o.link]; break;
      case "update_link": links = links.map(l => (l.id === o.id ? { ...l, ...o.fields } : l)); break;
      case "remove_link": links = links.filter(l => l.id !== o.id); break;
    }
  }
  return { ...page, version: patch.version, widgets, links };
}
