import { useEffect, useState } from "react";
import { api } from "../../api";

// Alfa-Business tip shown while the page is built: an AI sentence or two from the company card and the role. Any failure hides it.
export function AdTip({ company, role }: { company: string; role: string }) {
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    api.adTip({ company, role }).then(r => alive && setText(r.text)).catch(() => alive && setFailed(true));
    return () => { alive = false; };
  }, [company, role]);
  if (failed) return null;
  return (
    <aside className="adtip" aria-label="Реклама Альфа-Бизнеса">
      <div className="adtip-head"><b>Альфа-Бизнес</b><span>Реклама</span></div>
      {text ? <p>{text}</p> : <div className="adtip-skel" aria-hidden="true"><i /><i /></div>}
    </aside>
  );
}
