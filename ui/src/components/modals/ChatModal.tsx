import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api";
import type { ChatContext, ChatReply, Patch } from "../../api";

interface Msg { role: "ai" | "me" | "sys"; text: string; basis?: string[] }

interface Props {
  context: ChatContext;
  title: string;
  getVersion: () => number;
  onPatch: (p: Patch) => void;
  onStale: () => void;
  onClose: () => void;
}

export function ChatModal({ context, title, getVersion, onPatch, onStale, onClose }: Props) {
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
      const r = await api.chat({ context, session_id: session.current, message, page_version: getVersion() });
      session.current = r.session_id;
      const rep: ChatReply = r.reply;
      setMsgs(m => [...m, { role: "ai", text: rep.text, basis: rep.basis }]);
      setFollowups(rep.followups);
      if (r.patch) onPatch(r.patch);
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
            <div key={i} className={"m " + m.role}>
              {m.text}
              {!!m.basis?.length && <div className="basis">Основано на: {m.basis.join(" · ")}</div>}
            </div>
          ))}
          {busy && <div className="m sys">ИИ печатает…</div>}
          <div ref={end} />
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
