import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ChatContext, Column, Page, Patch } from "./api";
import { useCache } from "./lib/useCache";
import { applyPatch } from "./lib/patch";
import { computeFocus } from "./lib/focus";
import type { Hover } from "./lib/focus";
import { Header } from "./components/layout/Header";
import { StartMenu } from "./components/views/StartMenu";
import { Overview } from "./components/views/Overview";
import { Board } from "./components/views/Board";
import { AddBlockModal } from "./components/modals/AddBlockModal";
import { ArrowModal } from "./components/modals/ArrowModal";
import { ChatModal } from "./components/modals/ChatModal";
import { AskAiButton } from "./components/layout/AskAiButton";
import { ConfirmHomeModal } from "./components/modals/ConfirmHomeModal";
import { RiskModal } from "./components/modals/RiskModal";

export function App() {
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [hover, setHover] = useState<Hover>(null);
  const [chat, setChat] = useState<{ context: ChatContext; title: string } | null>(null);
  const [arrowId, setArrowId] = useState<string | null>(null);
  const [riskId, setRiskId] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [confirmHome, setConfirmHome] = useState<string | null>(null); // id of the last open widget awaiting "back to menu?"
  const [addCol, setAddCol] = useState<Column | null>(null); // column whose "add block" list is open
  const [section, setSection] = useState<Column>("news");
  const [profile, setProfile] = useState<string | null>(() => { try { return localStorage.getItem("profile"); } catch { return null; } }); // key of the page built for the user's company and role

  const [noPage, setNoPage] = useState(false); // "Ask AI" pressed before any page exists
  const [menu, setMenu] = useState(!profile); // the start menu comes before any analytics; "demo" leaves it without a profile

  const boardRef = useRef<HTMLElement>(null);
  const nodes = useRef(new Map<string, HTMLElement>());
  const pageRef = useRef<Page | null>(null);
  pageRef.current = page;

  const widgets = useCache(api.widget), risks = useCache(api.risks), links = useCache(api.link);

  const loadPage = useCallback(() => {
    setError(false);
    api.page(profile).then(p => { widgets.reset(); risks.reset(); links.reset(); setPage(p); }).catch(() => setError(true));
  }, [profile, widgets.reset, risks.reset, links.reset]);
  useEffect(loadPage, [loadPage]);

  useEffect(() => {
    if (!boardRef.current) return;
    const ro = new ResizeObserver(() => setTick(t => t + 1));
    ro.observe(boardRef.current);
    return () => ro.disconnect();
  }, [page !== null]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setChat(null); setArrowId(null); setRiskId(null); setConfirmHome(null); setAddCol(null); } };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, []);

  const onPatch = (patch: Patch): Page | null => {
    const cur = pageRef.current!, next = applyPatch(cur, patch);
    if (!next) { loadPage(); return null; }
    setPage(next);
    // Cached details of changed items are stale; open widgets are re-fetched right away
    for (const o of patch.ops) {
      if (o.op === "update_widget") { widgets.drop(o.id); risks.drop(o.id); if (open.has(o.id)) widgets.load(o.id, true); }
      if (o.op === "remove_widget") { widgets.drop(o.id); risks.drop(o.id); setOpen(s => { const n = new Set(s); n.delete(o.id); return n; }); }
      if (o.op === "update_link" || o.op === "remove_link") links.drop(o.id);
    }
    return cur;
  };

  // shortcut: the rollback is local, the server keeps the patched page until it has an undo endpoint (issue #25 list)
  const onUndo = (before: Page) => {
    widgets.reset(); risks.reset(); links.reset();
    setOpen(new Set()); setPage({ ...before, version: pageRef.current!.version });
  };

  // One entry point for any screen: asks about the only open widget, else the first one of the page
  const askAi = () => {
    const p = pageRef.current;
    const w = p && (p.widgets.find(x => open.size === 1 && open.has(x.id)) ?? p.widgets[0]);
    if (w) setChat({ context: { type: "widget", id: w.id }, title: open.size === 1 ? w.title : "вся страница" });
    else { setNoPage(true); setTimeout(() => setNoPage(false), 3000); }
  };

  const toggle = (id: string) => {
    if (open.size === 1 && open.has(id)) return setConfirmHome(id); // closing the last widget leaves focus mode: ask first
    setOpen(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
    widgets.load(id);
  };

  const selectProfile = (key: string) => {
    try { localStorage.setItem("profile", key); } catch { /* storage may be blocked */ }
    setOpen(new Set()); setProfile(key); setMenu(false);
  };

  const ask = <>{noPage && <div className="ask-hint">Сначала откройте аналитику: ИИ отвечает по странице.</div>}<AskAiButton onClick={askAi} /></>;
  if (menu) return <><StartMenu onReady={selectProfile} onDemo={() => { setProfile(null); setMenu(false); }} />{ask}</>;
  if (error) return <div className="state" style={{ color: "#fff", padding: 28 }}>Не удалось загрузить страницу<button onClick={loadPage}>Повторить</button>{ask}</div>;
  if (!page) return <div className="state" style={{ color: "#fff", padding: 28 }}>Загрузка…{ask}</div>;

  const title = (id: string) => page.widgets.find(w => w.id === id)?.title ?? id;
  const linkTitle = (id: string) => { const l = page.links.find(x => x.id === id); return l ? `${title(l.from)} → ${title(l.to)}` : id; };
  const { hlLinks, hlWidgets, selected, hidden, visibleLinks } = computeFocus(page, open, hover);

  return (
    <>
      <Header company={page.company} demo={!profile} onMenu={() => setMenu(true)} />
      {!selected.length ? (
        <Overview widgets={page.widgets} details={widgets.entries} section={section} onSection={setSection} onToggle={toggle} />
      ) : (
        <Board
          widgets={page.widgets} details={widgets.entries} open={open} hidden={hidden} hlWidgets={hlWidgets} hlLinks={hlLinks}
          visibleLinks={visibleLinks} dim={!!hover} tick={tick} boardRef={boardRef} nodes={nodes}
          onToggle={toggle} onRetry={id => widgets.load(id, true)}
          onChat={w => setChat({ context: { type: "widget", id: w.id }, title: w.title })}
          onRisks={id => { risks.load(id); setRiskId(id); }}
          onHoverWidget={id => setHover(id ? { type: "widget", id } : null)}
          onHoverLink={id => setHover(id ? { type: "link", id } : null)}
          onArrow={id => { links.load(id); setArrowId(id); }} onAdd={setAddCol}
        />
      )}
      <p className="note">demo</p>
      {ask}

      {addCol && (
        <AddBlockModal
          col={addCol} widgets={page.widgets.filter(w => w.column === addCol && hidden.has(w.id))}
          onPick={id => { toggle(id); setAddCol(null); }} onClose={() => setAddCol(null)}
        />
      )}
      {confirmHome && <ConfirmHomeModal onConfirm={() => { setOpen(new Set()); setConfirmHome(null); }} onClose={() => setConfirmHome(null)} />}
      {chat && (
        <ChatModal
          key={chat.context.type + chat.context.id} context={chat.context} title={chat.title}
          getPage={() => pageRef.current!} onPatch={onPatch} onUndo={onUndo} onStale={loadPage} onClose={() => setChat(null)}
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
