import { useLayoutEffect, useState } from "react";
import type { RefObject } from "react";
import type { LinkSkeleton } from "../types";

interface Props {
  boardRef: RefObject<HTMLElement | null>;
  nodes: RefObject<Map<string, HTMLElement>>;
  links: LinkSkeleton[];
  active: Set<string>;
  onHover: (id: string | null) => void;
  onClick: (id: string) => void;
  tick: number; // bumped by the board when its size changes
}

interface Drawn { id: string; d: string; head: string }

export function Arrows({ boardRef, nodes, links, active, onHover, onClick, tick }: Props) {
  const [drawn, setDrawn] = useState<Drawn[]>([]);

  // Runs after every render so arrows follow expanding/collapsing widgets; state is only set when paths change.
  useLayoutEffect(() => {
    const board = boardRef.current;
    if (!board) return;
    const b = board.getBoundingClientRect();
    const rect = (id: string) => {
      const r = nodes.current.get(id)?.getBoundingClientRect();
      return r && { l: r.left - b.left, r: r.right - b.left, t: r.top - b.top, h: r.height };
    };
    const slots = new Map<string, string[]>(); // spread endpoints along the edge so arrows don't overlap
    for (const l of links) {
      for (const key of [l.from + ">", l.to + "<"]) slots.set(key, [...(slots.get(key) ?? []), l.id]);
    }
    const ypos = (wid: string, side: string, lid: string) => {
      const a = slots.get(wid + side)!, r = rect(wid)!;
      return r.t + (r.h * (a.indexOf(lid) + 1)) / (a.length + 1);
    };
    const next: Drawn[] = [];
    for (const l of links) {
      const f = rect(l.from), t = rect(l.to);
      if (!f || !t) continue;
      const x1 = f.r, x2 = t.l - 8, y1 = ypos(l.from, ">", l.id), y2 = ypos(l.to, "<", l.id), dx = (x2 - x1) / 2;
      next.push({
        id: l.id,
        d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`,
        head: `M${x2},${y2 - 7} L${x2 + 10},${y2} L${x2},${y2 + 7}Z`,
      });
    }
    setDrawn(prev => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  });
  void tick;

  return (
    <svg className="arrows">
      {drawn.map(a => (
        <g key={a.id} className={active.has(a.id) ? "on" : ""} onMouseEnter={() => onHover(a.id)} onMouseLeave={() => onHover(null)} onClick={() => onClick(a.id)}>
          <path className="a" d={a.d} />
          <path className="head" d={a.head} />
          <path className="hit" d={a.d} />
        </g>
      ))}
    </svg>
  );
}
