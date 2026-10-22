import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useCache } from "./cache";
import { applyPatch } from "./patch";
import type { ChatContext, Column, Page, Patch } from "./types";
import { ArrowModal } from "./components/ArrowModal";
import { Arrows } from "./components/Arrows";
import { ChatModal } from "./components/ChatModal";
import { RiskModal } from "./components/RiskModal";
import { Widget } from "./components/Widget";

const COLUMNS: [Column, string, string][] = [
  ["news", "Самые важные новости", "Что произошло"],
  ["analytics", "Аналитика", "Что это значит для компании"],
  ["decisions", "Советуемые решения", "Что можно сделать"],
];

type Hover = { type: "widget" | "link"; id: string } | null;

export function App() {
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [hover, setHover] = useState<Hover>(null);
  const [chat, setChat] = useState<{ context: ChatContext; title: string } | null>(null);
  const [arrowId, setArrowId] = useState<string | null>(null);
  const [riskId, setRiskId] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const boardRef = useRef<HTMLElement>(null);
  const nodes = useRef(new Map<string, HTMLElement>());
  const pageRef = useRef<Page | null>(null);
  pageRef.current = page;

  const widgets = useCache(api.widget), risks = useCache(api.risks), links = useCache(api.link);

  const loadPage = useCallback(() => {
    setError(false);
    api.page().then(p => { widgets.reset(); risks.reset(); links.reset(); setPage(p); }).catch(() => setError(true));
  }, [widgets.reset, risks.reset, links.reset]);
  useEffect(loadPage, []);

  useEffect(() => {
    if (!boardRef.current) return;
    const ro = new ResizeObserver(() => setTick(t => t + 1));
    ro.observe(boardRef.current);
    return () => ro.disconnect();
  }, [page !== null]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setChat(null); setArrowId(null); setRiskId(null); } };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, []);

  const onPatch = (patch: Patch) => {
    const cur = pageRef.current!, next = applyPatch(cur, patch);
    if (!next) return loadPage();
    setPage(next);
    // Cached details of changed items are stale; open widgets are re-fetched right away
    for (const o of patch.ops) {
      if (o.op === "update_widget") { widgets.drop(o.id); risks.drop(o.id); if (open.has(o.id)) widgets.load(o.id, true); }
      if (o.op === "remove_widget") { widgets.drop(o.id); risks.drop(o.id); setOpen(s => { const n = new Set(s); n.delete(o.id); return n; }); }
      if (o.op === "update_link" || o.op === "remove_link") links.drop(o.id);
    }
  };

  const toggle = (id: string) => {
    setOpen(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
    widgets.load(id);
  };

  if (error) return <div className="state" style={{ color: "#fff", padding: 28 }}>Не удалось загрузить страницу<button onClick={loadPage}>Повторить</button></div>;
  if (!page) return <div className="state" style={{ color: "#fff", padding: 28 }}>Загрузка…</div>;

  const title = (id: string) => page.widgets.find(w => w.id === id)?.title ?? id;
  const linkTitle = (id: string) => { const l = page.links.find(x => x.id === id); return l ? `${title(l.from)} → ${title(l.to)}` : id; };
  const hlLinks = new Set<string>(), hlWidgets = new Set<string>();
  if (hover?.type === "link") {
    const l = page.links.find(x => x.id === hover.id);
    if (l) { hlLinks.add(l.id); hlWidgets.add(l.from).add(l.to); }
  } else if (hover) {
    hlWidgets.add(hover.id);
    page.links.filter(l => l.from === hover.id || l.to === hover.id).forEach(l => hlLinks.add(l.id));
  }
  // Focus mode: an open widget leaves only open widgets in its column; every column to the left
  // keeps only widgets that lead to what stays visible in the next column.
  const hidden = new Set<string>();
  let vis: Set<string> | null = null;
  for (let i = COLUMNS.length - 1; i >= 0; i--) {
    const ids = page.widgets.filter(w => w.column === COLUMNS[i][0]).map(w => w.id);
    const opened = ids.filter(id => open.has(id));
    if (opened.length) vis = new Set(opened);
    else if (vis) { const next: Set<string> = vis; vis = new Set(ids.filter(id => page.links.some(l => l.from === id && next.has(l.to)))); }
    if (vis) ids.filter(id => !vis!.has(id)).forEach(id => hidden.add(id));
  }
  const visibleLinks = page.links.filter(l => !hidden.has(l.from) && !hidden.has(l.to));
  const c = page.company;

  return (
    <>
      <header>
        <h1>Новостная аналитика для принятия решений</h1>
        <div className="chips">
          {[c.name, "ОКВЭД " + c.okved, "Роль: " + c.role, c.date].map(t => <span className="chip" key={t}>{t}</span>)}
          <span className="chip demo">демо-данные</span>
        </div>
      </header>
      <main className={"board" + (hover ? " dim" : "")} ref={boardRef}>
        {COLUMNS.map(([col, head, sub], i) => (
          <section className={`col c${i + 1}`} key={col}>
            <div className="col-head">{head}<small>{sub}</small></div>
            {page.widgets.filter(w => w.column === col && !hidden.has(w.id)).map(w => (
              <Widget
                key={w.id} w={w} details={widgets.entries[w.id]} open={open.has(w.id)} highlighted={hlWidgets.has(w.id)}
                nodeRef={el => { el ? nodes.current.set(w.id, el) : nodes.current.delete(w.id); }}
                onToggle={() => toggle(w.id)} onRetry={() => widgets.load(w.id, true)}
                onChat={() => setChat({ context: { type: "widget", id: w.id }, title: w.title })}
                onRisks={() => { risks.load(w.id); setRiskId(w.id); }}
                onHover={on => setHover(on ? { type: "widget", id: w.id } : null)}
              />
            ))}
          </section>
        ))}
        <Arrows
          boardRef={boardRef} nodes={nodes} links={visibleLinks} active={hlLinks} tick={tick}
          onHover={id => setHover(id ? { type: "link", id } : null)}
          onClick={id => { links.load(id); setArrowId(id); }}
        />
      </main>
      <p className="note">demo</p>

      {chat && (
        <ChatModal
          key={chat.context.type + chat.context.id} context={chat.context} title={chat.title}
          getVersion={() => pageRef.current!.version} onPatch={onPatch} onStale={loadPage} onClose={() => setChat(null)}
        />
      )}
      {arrowId && (
        <ArrowModal
          title={linkTitle(arrowId)} entry={links.entries[arrowId]} onClose={() => setArrowId(null)}
          onAsk={() => { setChat({ context: { type: "link", id: arrowId }, title: "Связь: " + linkTitle(arrowId) }); setArrowId(null); }}
        />
      )}
      {riskId && <RiskModal title={title(riskId)} entry={risks.entries[riskId]} onRetry={() => risks.load(riskId, true)} onAsk={() => { setChat({ context: { type: "widget", id: riskId }, title: title(riskId) }); setRiskId(null); }} onClose={() => setRiskId(null)} />}
    </>
  );
}
