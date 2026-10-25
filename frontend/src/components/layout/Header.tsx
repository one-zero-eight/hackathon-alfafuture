import type { Company } from "../../api";

export function Header({ company: c, demo, onMenu }: { company: Company; demo: boolean; onMenu: () => void }) {
  return (
    <header>
      <h1>Новостная аналитика для принятия решений</h1>
      <div className="chips">
        {[c.name, c.okved && c.okved !== "не указан" ? "ОКВЭД " + c.okved : "", "Роль: " + c.role, c.date].filter(Boolean).map(t => <span className="chip" key={t}>{t}</span>)}
        {demo && <span className="chip demo">демо-данные</span>}
      </div>
      <button className="back-menu" onClick={onMenu}>Сменить компанию</button>
    </header>
  );
}
