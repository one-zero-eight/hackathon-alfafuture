import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import type { CompanyItem, ProfileStatus } from "../../api";
import { Timeline } from "../layout/Timeline";
import { AdTip } from "../widgets/AdTip";

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
const PAGE = 50;

// Start menu: pick a company from the bank data (left), describe the role (right), then watch the page being built.
export function StartMenu({ onReady, onDemo }: { onReady: (key: string) => void; onDemo: () => void }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<CompanyItem[]>([]);
  const [total, setTotal] = useState(0);
  const [listError, setListError] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [role, setRole] = useState("");
  const [progress, setProgress] = useState<ProfileStatus | null>(null);
  const [error, setError] = useState("");
  const loading = useRef(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const load = (query: string, offset: number) => {
    if (loading.current) return;
    loading.current = true;
    api.companies(query, offset, PAGE)
      .then(r => { setListError(false); setTotal(r.total); setItems(cur => (offset ? [...cur, ...r.items] : r.items)); })
      .catch(() => setListError(true))
      .finally(() => { loading.current = false; });
  };
  useEffect(() => {
    const t = setTimeout(() => load(q, 0), q ? 250 : 0); // wait for the typing to stop
    return () => clearTimeout(t);
  }, [q]);

  const onScroll = (e: React.UIEvent<HTMLUListElement>) => {
    const el = e.currentTarget;
    if (items.length < total && el.scrollTop + el.clientHeight > el.scrollHeight - 120) load(q, items.length);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!picked) return;
    setError(""); setProgress({ key: "", status: "queued", error: "" });
    try {
      let s = await api.setProfile({ company: picked, role });
      while (alive.current && (s.status === "queued" || s.status === "running")) {
        setProgress(s); await sleep(1500); s = await api.profileStatus(s.key);
      }
      if (!alive.current) return;
      if (s.status === "ready") return onReady(s.key); // a cached page is ready at once, the timeline never shows
      setError("Не получилось: " + (s.error || "ошибка сервера"));
    } catch { setError("Не удалось связаться с сервером"); }
    setProgress(null);
  };

  if (progress) {
    return (
      <main className="menu menu-busy">
        <h2>Собираем аналитику</h2>
        <Timeline status={progress} />
        {picked && <AdTip company={picked} role={role.trim()} />}
        <p className="menu-hint">Первый запуск компании занимает несколько минут, повторные берутся из базы.</p>
      </main>
    );
  }

  return (
    <main className="menu">
      <section className="menu-list">
        <h2>Компания</h2>
        <input type="search" placeholder="Поиск по ID или отрасли" value={q} onChange={e => setQ(e.target.value)} aria-label="Поиск компании" />
        <ul onScroll={onScroll} role="listbox" aria-label="Список компаний">
          {items.map(c => (
            <li key={c.id} role="option" aria-selected={c.id === picked} className={c.id === picked ? "on" : ""} tabIndex={0}
                onClick={() => setPicked(c.id)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPicked(c.id); } }}>
              {c.id}: {c.okved_name}
            </li>
          ))}
          {listError && <li className="menu-note">Не удалось загрузить список <button type="button" onClick={() => load(q, items.length)}>Повторить</button></li>}
          {!listError && !items.length && <li className="menu-note">{loading.current ? "Загрузка…" : "Ничего не найдено"}</li>}
        </ul>
        <span className="menu-count">{total ? `Показано ${items.length} из ${total}` : ""}</span>
      </section>

      <form className="menu-role" onSubmit={submit}>
        <h2>Ваша роль в компании</h2>
        <textarea value={role} onChange={e => setRole(e.target.value)} maxLength={200} required rows={6}
                  placeholder="Например: отвечаю за выбор поставщиков для магазинов в ЦФО" aria-label="Роль сотрудника" />
        <button disabled={!picked || !role.trim()}>Сбор новостей</button>
        {!picked && <span className="menu-hint">Выберите компанию в списке слева</span>}
        {error && <span className="menu-error">{error}</span>}
        <button type="button" className="menu-demo" onClick={onDemo}>Посмотреть демо</button>
      </form>
    </main>
  );
}
