# Memo U14: CEO, software development and IT services (OKVED J), Moscow, small, salary payments

Assumptions: our tech stack, hosting region and vendors are not in the items. Confirm before acting.

## 1. Decisions now

1. **Patch PHP on all client and internal sites now.** Owner: CTO. Items: A1507 (two critical PHP vulnerabilities announced 20 Oct; government sites switched off in several countries), A1460 and A1730 (risk to Runet sites). Check (rule 4): is our stack PHP and is it exposed? Ask the lead engineer today.

2. **Check the cloud region our services depend on and set up a fallback.** Owner: CTO. Items: A0494 (Revolut outage), A0691 (Google Cloud London outage hit services across Europe). Check (rule 4): is our hosting in the affected region? Confirm, then add a second region or provider if the answer is yes.

3. **Harden customer login and transfer flows against account takeover.** Owner: security lead. Items: A0164 (a single case of RUB 450 million lost to fraud in Moscow), A0502 (teen involvement in cybercrime up 30% in 2026). Check (rule 3): applies to any client-facing login we run.

4. **Check whether any product or model we use comes from a vendor the US has banned.** Owner: CTO. Items: A0305 (US agencies told to remove DeepSeek products), A0809 (DeepSeek app ranked first in several countries). Check (rule 5): do we use or resell these models? The items do not say.

## 2. Monitor

- Telecom licensing reform (A1633) and ministry network-protection HQ (A1527, A0884). Trigger: a licensing or protection requirement that reaches software vendors, then review obligations.
- Cybersecurity demand rising in government (A1413, A1495). Trigger: a public tender that asks for our services, then assess fit.

## 3. Deliberately not acting on

- Starlink speed limits for Ukraine (A0936, A0715, A1517): no effect on our business.
- Steam outage (A1277): consumer platform; no effect on us.
- Anthropic loss figures (A0831): a vendor's financials, not a trigger.
- Shares of a Russian security firm after a breach report (A0478): market move, not our action.
