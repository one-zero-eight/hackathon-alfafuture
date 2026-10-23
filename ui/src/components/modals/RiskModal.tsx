import { useState } from "react";
import type { Entry } from "../../lib/useCache";
import type { RiskInfo } from "../../api";

const PL = ["Редкая", "Возможная", "Вероятная", "Почти неизбежная"];
const IL = ["Незначительный", "Умеренный", "Существенный", "Критический"];
const score = (p: number, i: number) => { const s = p * i; return s <= 3 ? 1 : s <= 6 ? 2 : s <= 9 ? 3 : 4; };

interface Props { title: string; entry?: Entry<RiskInfo>; onRetry: () => void; onAsk: () => void; onClose: () => void }

export function RiskModal({ title, entry, onRetry, onAsk, onClose }: Props) {
  const [on, setOn] = useState<number | null>(null);
  const r = entry?.data;
  return (
    <div className="ov open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal wide">
        <div className="mh"><h2>{title}</h2><button className="x" aria-label="Закрыть" onClick={onClose}>✕</button></div>
        {!r ? (
          <div className="state" style={{ padding: "6px 22px 22px" }}>
            {entry?.status === "error" ? <>Не удалось загрузить<button onClick={onRetry}>Повторить</button></> : "Загрузка…"}
          </div>
        ) : (
          <div className="rbody">
            <div>
              <h4>Что сделать</h4>
              <ul>{r.steps.map(s => <li key={s}>{s}</li>)}</ul>
              {r.bank_offer && <div className="ad"><b>Альфа-Бизнес.</b> {r.bank_offer}</div>}
              <h4 style={{ marginTop: 14 }}>Риск-менеджмент</h4>
              <div className="rl">
                {r.risks.map((k, n) => (
                  <div className="ri" key={k.name} onMouseEnter={() => setOn(n)} onMouseLeave={() => setOn(null)}>
                    <span className="dot">{n + 1}</span><div><b>{k.name}</b><br />{k.mitigation}</div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h4>Матрица рисков 4×4 (вертикаль — влияние, горизонталь — вероятность)</h4>
              <div className="mx">
                {[4, 3, 2, 1].flatMap(i => [
                  <div key={"y" + i} className="ax y">{IL[i - 1]}</div>,
                  ...[1, 2, 3, 4].map(p => (
                    <div key={`${p}${i}`} className={"cell s" + score(p, i)}>
                      {r.risks.map((k, n) => k.probability === p && k.impact === i && (
                        <span key={n} className={"dot" + (on === n ? " on" : "")} onMouseEnter={() => setOn(n)} onMouseLeave={() => setOn(null)}>{n + 1}</span>
                      ))}
                    </div>
                  )),
                ])}
                <div />
                {PL.map(p => <div key={p} className="ax">{p}</div>)}
              </div>
              <div style={{ marginTop: 14, textAlign: "right" }}><button onClick={onAsk}>Спросить ИИ</button></div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
