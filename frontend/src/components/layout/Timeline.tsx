import type { ProfileStatus } from "../../api";
import { steps } from "../../lib/stages";

// Vertical timeline of the page build: done steps are checked, the active one pulses.
export function Timeline({ status }: { status: Pick<ProfileStatus, "status" | "stage" | "found" | "selected"> }) {
  return (
    <ol className="timeline" aria-live="polite">
      {steps(status).map(s => (
        <li key={s.label.slice(0, 8)} className={"tl-" + s.state}>
          <span className="tl-dot" aria-hidden="true">{s.state === "done" ? "✓" : ""}</span>
          <span className="tl-label">{s.label}</span>
        </li>
      ))}
    </ol>
  );
}
