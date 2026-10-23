import type { Company } from "../../api";
import { ProfileForm } from "./ProfileForm";

export function Header({ company: c, demo, onProfile }: { company: Company; demo: boolean; onProfile: (key: string) => void }) {
  return (
    <header>
      <h1>Новостная аналитика для принятия решений</h1>
      <div className="chips">
        {[c.name, c.okved && c.okved !== "не указан" ? "ОКВЭД " + c.okved : "", "Роль: " + c.role, c.date].filter(Boolean).map(t => <span className="chip" key={t}>{t}</span>)}
        {demo && <span className="chip demo">демо-данные</span>}
      </div>
      <ProfileForm onReady={onProfile} />
    </header>
  );
}
