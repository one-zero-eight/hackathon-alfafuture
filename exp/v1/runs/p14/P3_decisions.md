# GC Memo: Week of 21 October 2026

## 1. Decisions now

1. **Marking expansion, live 1 Nov (10 days).** Issue a seller notice by 26 Oct listing the newly added "Честный знак" categories (A1801). Block listings in those categories without valid codes from 1 Nov. Owner: Head of Seller Compliance. Transmission: stricter obligations apply on a fixed date, so no 30-60 day runway exists. Check: enacted, effective date fixed, so act immediately (playbook 6). Pair with the Metro fine for unlabelled goods (A0776) as a unified rollout (pattern c).

2. **Return-policy audit against the Sept retail rules (A1941).** Compare customer and seller return terms with the updated non-returnable list by 5 Nov. Fix mismatches in 14 days. Transmission: the list is already in force, so this is catch-up, not preparation. Check: enacted and in effect (playbook 7).

3. **PHP exposure (A1730, A1902, A1674).** Within 48h, confirm the PHP patch level on all customer-facing hosts and apply fixes or a WAF rule where patches are not yet available. Prepare a breach notice that meets the 24-72h reporting window. Owner: CTO with GC. Transmission: a web-stack compromise would expose customer personal data. Check: Russian regime governs; direction is rising, since exploits are now AI-assisted.

4. **Remove manipulative urgency (A1035).** Within 14 days, remove countdown timers and unverifiable stock counters from our own pages and from seller templates. Owner: Product and Marketing. Check: no enacted rule yet, so this is voluntary and reversible, which preempts consumer-protection action (playbook 6).

5. **Freeze contested promo and ranking terms (A0443, A0768).** Pause changes to our own promotion-eligibility and ranking rules. Compile documented rationale for current terms within 30 days, since FAS complaints about Ozon promos are rising. Check: complaints target a platform's terms, so tightening ours now raises exposure (pattern d, playbook 5).

6. **Lobbying window on platform law (A0768).** Submit a position through the marketplace association before the Duma committee schedules a reading. Target: fee transparency and seller dispute rights. No contract amendments until the law is adopted (playbook 1).

7. **Brand-impersonation controls (A0762, A0788).** Run weekly lookalike-domain scans for our brands. Add a prepayment-fraud warning to checkout and order notifications by 31 Oct. Check: share of brand-mimicking resources fell from 8.4% to 5.7%, but losses still rose, so keep the scan.

8. **Platform and cloud resilience (A0595, A0691, A0421).** Review SLA and force-majeure clauses in ad-platform and cloud contracts within 30 days. Co-sign the association's emergency-trading letter (A0421). Check: outages are operational, not regulatory, so this is clause-level work only (playbook 9).

## 2. Monitor

- **A0592** (harsher penalties for calls to riots online): trigger is second reading. Then tighten notice-and-takedown for user content (playbook 7).
- **A1071** (banks reject transfers from infected phones from 1 March): trigger is any payment-provider notice. Then assess checkout failures (playbook 9).
- **A0293** (Ozon 1% fee for pickup-point owners from 1 Dec): trigger is any partner-point contract exposure. Then update partner terms (playbook 8).
- **A0853, A0586** (sellers shifting to Ozon): trigger is Ozon share above 60% in our own category data. Then review our own-brand allocation (playbook 8).

## 3. Deliberately not acting on

- **A1913** (Meta fine, US): foreign case, Meta banned in Russia, no direct transmission.
- **A0367** (French resale rules): foreign jurisdiction.
- **A1547, A0286, A0572, A1091** (fuel exchange, FAS on energy and gas): different sectors.
- **A1261, A1187, A1032** (shopping as leisure): sentiment, no rule change.
- **A0112, A0305, A1463** (DDoS trend, DeepSeek ban, Lukoil assets): no transmission to our business.
