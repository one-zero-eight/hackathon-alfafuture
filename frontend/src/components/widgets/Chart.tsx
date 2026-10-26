import type { ChartData } from "../../api";

const W = 300, H = 130, PL = 30, PR = 8, PT = 16, PB = 22;

export function Chart({ c }: { c: ChartData }) {
  const all = c.series.flatMap(s => s.values), max = Math.max(...all);
  const min = c.type === "line" ? Math.min(...all) * 0.9 : 0, n = c.labels.length;
  const y = (v: number) => PT + (H - PT - PB) * (1 - (v - min) / (max - min || 1));
  const tk = (v: number) => (max - min > 10 ? Math.round(v) : Math.round(v * 10) / 10);
  const gw = (W - PL - PR) / n, bw = gw / (c.series.length + 1);
  const lx = (i: number) => PL + 20 + (i * (W - PL - PR - 40)) / Math.max(n - 1, 1);
  return (
    <div className="chart">
      <div className="legend">
        {c.series.map(s => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`}>
        {[min, (min + max) / 2, max].map(t => (
          <g key={t}>
            <line x1={PL} x2={W - PR} y1={y(t)} y2={y(t)} stroke="var(--color-light-neutral-300)" />
            <text x={PL - 4} y={y(t) + 4} textAnchor="end" style={{ fill: "var(--color-light-text-secondary)" }}>{tk(t)}</text>
          </g>
        ))}
        <path d={`M${PL},${PT} V${H - PB} H${W - PR}`} fill="none" stroke="var(--color-light-neutral-500)" />
        {c.type === "bars"
          ? c.labels.map((l, i) => (
              <g key={l}>
                {c.series.map((s, k) => {
                  const x = PL + i * gw + bw / 2 + k * bw, v = s.values[i];
                  return (
                    <g key={s.name}>
                      <rect x={x} y={y(v)} width={bw - 3} height={H - PB - y(v)} rx={4} fill={s.color} />
                      <text x={x + (bw - 3) / 2} y={y(v) - 3} textAnchor="middle">{v}</text>
                    </g>
                  );
                })}
                <text x={PL + i * gw + gw / 2} y={H - 6} textAnchor="middle">{l}</text>
              </g>
            ))
          : <>
              {c.series.map((s, k) => (
                <g key={s.name}>
                  <polyline fill="none" stroke={s.color} strokeWidth={3} points={s.values.map((v, i) => `${lx(i)},${y(v)}`).join(" ")} />
                  {s.values.map((v, i) => (
                    <g key={i}>
                      <circle cx={lx(i)} cy={y(v)} r={4} fill={s.color} />
                      {i > 0 && <text x={lx(i)} y={y(v) + (k === 0 ? -8 : 15)} textAnchor="middle">{v}</text>}
                    </g>
                  ))}
                </g>
              ))}
              {c.labels.map((l, i) => <text key={l} x={lx(i)} y={H - 6} textAnchor="middle">{l}</text>)}
            </>}
      </svg>
      <div className="cap">{c.unit}{c.demo ? " · демо-данные" : ""}</div>
    </div>
  );
}
