import type { Entry } from "../cache";
import type { LinkDetails } from "../types";

interface Props { title: string; entry?: Entry<LinkDetails>; onAsk: () => void; onClose: () => void }

export function ArrowModal({ title, entry, onAsk, onClose }: Props) {
  return (
    <div className="ov open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="mh"><h2>{title}</h2></div>
        <p style={{ margin: 0, padding: "6px 22px 14px" }}>
          {entry?.data?.text ?? (entry?.status === "error" ? "Не удалось загрузить описание связи." : "Загрузка…")}
        </p>
        <div style={{ padding: "0 22px 18px" }}>
          <button onClick={onAsk}>Спросить</button> <button className="alt" onClick={onClose}>Закрыть</button>
        </div>
      </div>
    </div>
  );
}
