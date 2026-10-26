import { Fragment } from "react";
import type { Column, WidgetSkeleton } from "../../api";
import type { Entry } from "../../lib/useCache";
import type { WidgetDetails } from "../../api";
import { COLUMNS } from "../../lib/columns";
import { Widget } from "../widgets/Widget";

const STEPS: [Column, string, string][] = [["news", "Новость", "что произошло"], ["analytics", "Аналитика", "что это значит для компании"], ["decisions", "Решение", "что можно сделать"]];

interface Props {
  widgets: WidgetSkeleton[]; details: Record<string, Entry<WidgetDetails>>;
  section: Column; onSection: (c: Column) => void; onToggle: (id: string) => void;
}

// Landing view: a one-section overview; clicking a card switches to the focus board
export function Overview({ widgets, details, section, onSection, onToggle }: Props) {
  return (
    <main className="overview">
      <div className="intro">
        <div className="flow">
          {STEPS.map(([col, name, hint], i) => (
            <Fragment key={col}>
              {i > 0 && <span className="flow-arrow">➝</span>}
              <button className={"flow-step" + (col === section ? " cur" : "")} onClick={() => onSection(col)}>
                <b>{name}</b><small>{hint}</small>
              </button>
            </Fragment>
          ))}
        </div>
        <p>
          Мы собираем новости, объясняем, что они значат для вашей компании, и предлагаем решения. Каждая карточка связана с теми, из которых она следует
          или к которым ведёт. Листайте разделы заголовками ниже. В разделе «Аналитика» видны все новости и все выводы.
          Нажмите на карточку, чтобы открыть доску: стрелки покажут, что из чего вытекает, и если открыта аналитика, колонка новостей остаётся целиком.
          Можно выбрать несколько карточек сразу; чтобы вернуться, снимите выбор.
        </p>
      </div>
      <div className="ring">
        {COLUMNS.map(([col, head, sub], i) => {
          const off = ((i - COLUMNS.findIndex(c => c[0] === section) + 4) % 3) - 1; // -1 left, 0 centre, 1 right
          return (
            <button key={col} className={"ring-item" + (off === 0 ? " cur" : "")} style={{ "--off": off } as React.CSSProperties}
              onClick={() => onSection(col)}>
              {head}<small>{sub}</small>
            </button>
          );
        })}
      </div>
      <div className="grid2" key={section}>
        {(section === "analytics"
          ? [...widgets.filter(w => w.column === "news"), ...widgets.filter(w => w.column === "analytics")]
          : widgets.filter(w => w.column === section)).map(w => (
          <Widget
            key={w.id} w={w} details={details[w.id]} open={false} highlighted={false}
            nodeRef={() => {}} onToggle={() => onToggle(w.id)} onRetry={() => {}} onChat={() => {}} onRisks={() => {}} onHover={() => {}}
          />
        ))}
      </div>
    </main>
  );
}
