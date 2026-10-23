import type { RefObject, MutableRefObject } from "react";
import type { Column, LinkSkeleton, WidgetDetails, WidgetSkeleton } from "../../api";
import type { Entry } from "../../lib/useCache";
import { COLUMNS } from "../../lib/columns";
import { Arrows } from "../graph/Arrows";
import { Widget } from "../widgets/Widget";

interface Props {
  widgets: WidgetSkeleton[]; details: Record<string, Entry<WidgetDetails>>;
  open: Set<string>; hidden: Set<string>; hlWidgets: Set<string>; hlLinks: Set<string>; visibleLinks: LinkSkeleton[];
  dim: boolean; tick: number;
  boardRef: RefObject<HTMLElement | null>; nodes: MutableRefObject<Map<string, HTMLElement>>;
  onToggle: (id: string) => void; onRetry: (id: string) => void; onChat: (w: WidgetSkeleton) => void; onRisks: (id: string) => void;
  onHoverWidget: (id: string | null) => void; onHoverLink: (id: string | null) => void; onArrow: (id: string) => void; onAdd: (col: Column) => void;
}

// Focus view: three columns of the opened cards and everything chained to them, with arrows between
export function Board(p: Props) {
  return (
    <main className={"board" + (p.dim ? " dim" : "")} ref={p.boardRef}>
      {COLUMNS.map(([col, head, sub], i) => (
        <section className={`col c${i + 1}`} key={col}>
          <div className="col-head">{head}<small>{sub}</small></div>
          {p.widgets.filter(w => w.column === col && !p.hidden.has(w.id)).map(w => (
            <Widget
              key={w.id} w={w} details={p.details[w.id]} open={p.open.has(w.id)} highlighted={p.hlWidgets.has(w.id)}
              nodeRef={el => { el ? p.nodes.current.set(w.id, el) : p.nodes.current.delete(w.id); }}
              onToggle={() => p.onToggle(w.id)} onRetry={() => p.onRetry(w.id)}
              onChat={() => p.onChat(w)} onRisks={() => p.onRisks(w.id)}
              onHover={on => p.onHoverWidget(on ? w.id : null)}
            />
          ))}
          {p.widgets.some(w => w.column === col && p.hidden.has(w.id)) && (
            <button className="add-btn" onClick={() => p.onAdd(col)}>+ Добавить блок</button>
          )}
        </section>
      ))}
      <Arrows
        boardRef={p.boardRef} nodes={p.nodes} links={p.visibleLinks} active={p.hlLinks} tick={p.tick}
        onHover={id => p.onHoverLink(id)} onClick={p.onArrow}
      />
    </main>
  );
}
