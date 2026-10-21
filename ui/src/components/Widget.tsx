import type { Entry } from "../cache";
import type { WidgetDetails, WidgetSkeleton } from "../types";
import { Chart } from "./Chart";
import { Tags } from "./Tags";

interface Props {
  w: WidgetSkeleton;
  details?: Entry<WidgetDetails>;
  open: boolean;
  highlighted: boolean;
  onToggle: () => void;
  onChat: () => void;
  onRisks: () => void;
  onRetry: () => void;
  onHover: (on: boolean) => void;
  nodeRef: (el: HTMLElement | null) => void;
}

export function Widget({ w, details, open, highlighted, onToggle, onChat, onRisks, onRetry, onHover, nodeRef }: Props) {
  const d = details?.data;
  const cls = ["w", open && "open", highlighted && "hl"].filter(Boolean).join(" ");
  return (
    <article className={cls} ref={nodeRef} onClick={onToggle} onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}>
      <h3>{w.title}</h3>
      <Tags tags={w.tags} />
      {open && (
        <div className="body">
          {details?.status === "loading" && !d && <div className="state">Загрузка…</div>}
          {details?.status === "error" && (
            <div className="state">Не удалось загрузить<button onClick={e => { e.stopPropagation(); onRetry(); }}>Повторить</button></div>
          )}
          {d && <>
            {d.src && (
              <div className="meta">
                {d.src} · {d.date}
                {w.url && <a className="srcbtn" href={w.url} target="_blank" rel="noopener" onClick={e => e.stopPropagation()}>источник</a>}
              </div>
            )}
            <p>{d.text}</p>
            {d.kpis && <div className="kpis">{d.kpis.map(k => <div className="kpi" key={k.label}><b>{k.value}</b><span>{k.label}</span></div>)}</div>}
            {d.chart && <Chart c={d.chart} />}
          </>}
          <div className="btns">
            <button onClick={e => { e.stopPropagation(); onChat(); }}>Спросить</button>
            {w.column === "decisions" && <button className="alt" onClick={e => { e.stopPropagation(); onRisks(); }}>Матрица рисков</button>}
          </div>
        </div>
      )}
    </article>
  );
}
