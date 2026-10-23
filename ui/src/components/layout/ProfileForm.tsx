import { useState } from "react";
import { api } from "../../api";

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

// Asks the server to build a page for (company, role) and waits until it is ready; the first run of a profile takes minutes, repeats are cached.
export function ProfileForm({ onReady }: { onReady: (key: string) => void }) {
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setMsg("Подбираем и анализируем новости, первый раз это занимает несколько минут…");
    try {
      let s = await api.setProfile({ company, role });
      while (s.status === "queued" || s.status === "running") { await sleep(3000); s = await api.profileStatus(s.key); }
      if (s.status === "ready") { setMsg(""); onReady(s.key); } else setMsg("Не получилось: " + (s.error || "ошибка сервера"));
    } catch { setMsg("Не удалось связаться с сервером"); }
    setBusy(false);
  };

  return (
    <form className="profile" onSubmit={submit}>
      <input placeholder="Компания" value={company} onChange={e => setCompany(e.target.value)} maxLength={200} required disabled={busy} />
      <input placeholder="Роль или сфера анализа" value={role} onChange={e => setRole(e.target.value)} maxLength={200} required disabled={busy} />
      <button disabled={busy}>{busy ? "Ждите…" : "Подобрать"}</button>
      {msg && <span className="profile-msg">{msg}</span>}
    </form>
  );
}
