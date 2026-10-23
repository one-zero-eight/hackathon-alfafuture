import type { Column, WidgetSkeleton } from "../../api";
import { COLUMNS } from "../../lib/columns";

// Lists the hidden cards of a column so one can be added to the focus view
export function AddBlockModal({ col, widgets, onPick, onClose }: { col: Column; widgets: WidgetSkeleton[]; onPick: (id: string) => void; onClose: () => void }) {
  return (
    <div className="ov open" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="mh"><h2>Добавить блок: {COLUMNS.find(c => c[0] === col)![1]}</h2><button className="x" onClick={onClose}>✕</button></div>
        <div className="pick">
          {widgets.map(w => (
            <div className="pick-row" key={w.id}>
              <span>{w.title}</span>
              <button title="Добавить" onClick={() => onPick(w.id)}>+</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
