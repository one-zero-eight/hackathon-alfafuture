# Memo U15: CEO, software development and IT services (OKVED J), Moscow, large, salary payments

Assumptions: our tech stack, hosting region, telecom licences and vendors are not in the items. Confirm before acting.

## 1. Decisions now

1. **Patch PHP across all client and internal systems within the week.** Owner: CTO. Items: A1507 (two critical PHP vulnerabilities; government sites taken offline across Europe), A1730 (risk to Runet sites), A1460. Check (rule 4): confirm whether our systems run PHP and whether they are exposed.

2. **Set up a multi-region fallback for critical services after the London cloud outage.** Owner: CTO with infrastructure lead. Items: A0691 (Google Cloud London outage hit European services), A0494 (Revolut outage). Check (rule 4): is our hosting in the affected region? Confirm, then add a second region.

3. **Brief the security team on account-takeover risk and tighten client-facing flows.** Owner: CISO. Items: A0164 (RUB 450 million lost in one Moscow fraud case), A0502 (teen cybercrime up 30% in 2026). Check (rule 3): applies to every client-facing login we run.

4. **Review vendor and model dependencies for any AI service the US has banned for agencies.** Owner: CTO. Items: A0305, A0809. Check (rule 5): do we use or resell these services? Confirm.

5. **Confirm whether any telecom licence we hold is in scope of the licensing reform.** Owner: legal. Items: A1633 (requirements on capital, network coverage and service quality). Check (rule 1): effective date and scope not stated. Ask.

## 2. Monitor

- Telecom licensing reform (A1633). Trigger: a draft bill, then assess obligations.
- Ministry network-protection HQ (A1527, A0884). Trigger: rules that reach software vendors, then review.
- Cybersecurity demand from government (A1413, A1495). Trigger: a tender that fits our services.

## 3. Deliberately not acting on

- Starlink speed limits (A0936, A0715): no effect on our business.
- Steam outage (A1277): consumer platform.
- AI bubble argument (A1242): market commentary, not a decision.
- Shares of a security firm after a breach report (A0478): market move, not our action.
