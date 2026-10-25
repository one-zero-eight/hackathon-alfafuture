import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import type { ChatContext, ChatReply, Page, Patch } from "../../api";
import { SCENARIO_LABEL, recognize, summarize } from "../../lib/scenario";
import type { Change } from "../../lib/scenario";

interface Msg { role: "ai" | "me" | "sys"; text: string; basis?: string[]; change?: { label: string; inferred: boolean; reason?: string; items: Change[]; undo: () => void; undone?: boolean } }

interface Props {
  context: ChatContext;
  title: string;
  getPage: () => Page;
  onPatch: (p: Patch) => Page | null; // returns the page before the patch, null when it forced a reload
  onUndo: (before: Page) => void;
  onStale: () => void;
  onClose: () => void;
}

export function ChatModal({ context, title, getPage, onPatch, onUndo, onStale, onClose }: Props) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [followups, setFollowups] = useState<string[]>([]);
  const [busy, setBusy] = useState(true);
  const [input, setInput] = useState("");
  const session = useRef<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const send = async (message: string | null) => {
    setBusy(true);
    if (message) setMsgs(m => [...m, { role: "me", text: message }]);
    try {
      const r = await api.chat({ context, session_id: session.current, message, page_version: getPage().version });
      session.current = r.session_id;
      const rep: ChatReply = r.reply;
      setMsgs(m => [...m, { role: "ai", text: rep.text, basis: rep.basis }]);
      setFollowups(rep.followups);
      const { scenario, inferred } = recognize(r.patch, r.scenario);
      const items = r.patch ? summarize(getPage(), r.patch) : [];
      const before = r.patch ? onPatch(r.patch) : null;
      if (r.patch) {
        const label = SCENARIO_LABEL[scenario.kind];
        const undo = () => { if (before) { onUndo(before); setMsgs(m => m.map(x => (x.change?.undo === undo ? { ...x, change: { ...x.change, undone: true } } : x))); } };
        setMsgs(m => [...m, { role: "ai", text: "", change: { label, inferred, reason: scenario.reason, items, undo: before ? undo : () => {} } }]);
      }
    } catch (e) {
      const stale = e instanceof ApiError && e.status === 409;
      setMsgs(m => [...m, { role: "sys", text: stale ? "Страница изменилась, обновляю. Повторите запрос." : "Не удалось получить ответ ИИ." }]);
      if (stale) onStale();
    }
    setBusy(false);
  };

  useEffect(() => { void send(null); }, []); // opening message
  useEffect(() => { end.current?.scrollIntoView(); }, [msgs]);

  const submit = (text: string) => { if (text.trim() && !busy) { setInput(""); void send(text.trim()); } };

  return (
    <div className="ov open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="mh"><h2>ИИ-аналитик · {title}</h2><button className="x" aria-label="Закрыть" onClick={onClose}>✕</button></div>
        <div className="msgs">
          {msgs.map((m, i) => (
            m.change ? (
              <div key={i} className="m change">
                <b>Сценарий: {m.change.label}{m.change.inferred && " (предположение интерфейса)"}</b>
                {m.change.reason && <div>{m.change.reason}</div>}
                {m.change.items.length ? <ul>{m.change.items.map((c, j) => <li key={j}>{{ added: "Добавлено", replaced: "Заменено", removed: "Удалено" }[c.kind]}: {c.title}</li>)}</ul> : <div>Состав блоков не изменился.</div>}
                <button disabled={m.change.undone} onClick={m.change.undo}>{m.change.undone ? "Откачено" : "Откатить"}</button>
              </div>
            ) : (
            <div key={i} className={"m " + m.role}>
              {m.text}
              {!!m.basis?.length && <div className="basis">Основано на: {m.basis.join(" · ")}</div>}
            </div>
            )
          ))}
          {busy && <div className="m sys">ИИ печатает…</div>}
          <div ref={end} />
        </div>
        <div className="chips-act">
          <button type="button" disabled={busy} onClick={() => submit("Удали эту новость как неактуальную")}>Удалить как неактуальное</button>
          <button type="button" disabled={busy} onClick={() => setInput("Добавь новость по ссылке: ")}>Вставить ссылку</button>
          <button type="button" disabled={busy} onClick={() => setInput("Исправь вывод: ")}>Исправить вывод</button>
        </div>
        <div className="fu">{followups.map(q => <button key={q} disabled={busy} onClick={() => submit(q)}>{q}</button>)}</div>
        <form className="chatform" onSubmit={e => { e.preventDefault(); submit(input); }}>
          <input autoFocus value={input} onChange={e => setInput(e.target.value)} placeholder="Задайте вопрос или попросите изменить аналитику…" />
          <button disabled={busy}>Отправить</button>
        </form>
      </div>
    </div>
  );
}
