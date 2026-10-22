# CISO Decision Memo - Week of 2026-10-21

## 1. Decisions now

1. **PHP emergency inventory and patch (owner: Head of AppSec + CIO, scope list in 24h).** Items: A1449, A1671, A1674, A1507, A1495, A1460, A1803. Path: mass takedowns of hospital and government sites over two critical PHP flaws; we likely run PHP in web properties and third-party portals. Check: reports say "critical", but exploitation status is not in the cards. So this is not yet playbook rule 1. Inventory internet-facing PHP now. Apply WAF rules or temporary disablement to exposed PHP-based assets, and patch on the 14-30 day cycle. Escalate to 24-72h if exploitation is confirmed. Do not raise the bank-wide alert level on this alone.

2. **Vendor and cloud concentration review (owner: Third-Party Risk, 48h).** Items: A0691, A0494, A0185, A1866. Path: a Google Cloud europe-west2 outage disrupted Revolut and other European services, so the same failure could hit our cloud-hosted services and suppliers. Check: this was an outage, not a compromise, so rule 4 applies only in part (DORA register and resilience, no isolation). Map which of our critical or important functions depend on that region. Request supplier attestations on multi-region failover. Test a failover scenario within 4 weeks.

3. **Payment-verification and deepfake/credential awareness push (owner: Fraud + Awareness, launch in 7 days).** Items: A0247, A1025, A0431. Path: AI agents compromise sites for about $50 each. 56% of pentest paths used valid credentials, and the AfD leak included ID photos and AI-generated summaries, which are material for social engineering. Check: the victims are mostly non-bank and outside our region, but the credential and deepfake risk applies to us (pattern d). Run a simulated phishing campaign, reinforce the payment callback procedure for payments above the set threshold, and enforce MFA and phishing-resistant authentication for privileged and remote access.

4. **Credential-abuse hardening (owner: IAM lead, 30 days).** Items: A1025, A0247. Path: valid credentials and authentication redirection drive most attack paths in the pentest data. Check: the data comes from a vendor with a commercial interest and is not specific to German banks. It is still consistent with our exposure, so act cheaply. Review stale and privileged accounts, tighten conditional access, and run an automated attack-path test on internet-facing systems.

5. **AI-tool policy update (owner: CISO + Legal, 14 days).** Items: A0305, A0247. Path: the US ordered removal of DeepSeek, citing multiple threat vectors, and attackers use autonomous AI agents. Staff may use unapproved or Chinese-origin AI tools. Check: the US order is informational only, since the EU/German regime governs. We act on the underlying risk, not on the order. Confirm the approved-tools list, block DeepSeek and similar unapproved services at the proxy, and reiterate that no customer data goes into public models. Request a legal view on GDPR and DORA.

6. **State-actor and political-leak monitoring (owner: SOC lead, 7 days).** Items: A0431, A1413, A1449, A0551. Path: the AfD mail leak, government sites taken offline in several European countries, and unrest in Europe raise the chance of hacktivist or state-linked activity. Check: the relevant effect is a higher chance of DDoS and defacement, and it is likely temporary. Set DDoS protection to elevated, confirm the provider runbook, brief the SOC on heightened watch, and schedule a tabletop exercise within 2-4 weeks (rule 8). Combine this with the PHP item as one tabletop scenario (a web-vulnerability wave plus DDoS).

7. **Employee and executive data-leak hygiene (owner: Privacy/DPO + CISO, 14 days).** Items: A0431. Path: the leak of 421k emails shows what mailbox compromise at an organization could expose, including scans of ID documents. Check: this concerns a political party, not a peer bank, so rule 9 does not apply. Review retention and storage of ID scans in mailboxes, and check high-risk accounts for MFA and mailbox forwarding.

## 2. Monitor
- Confirmed exploitation of the PHP flaws, or a CISA KEV listing: move to the 24-72h patch path and raise the alert level (A1449 and related).
- Any BSI or BaFin notice about the PHP wave, or takedowns of German banking sites: raise the alert level (A1495).
- A repeat Google Cloud europe-west2 incident, or a supplier outage reaching our services: invoke the DORA incident classification (A0691, A0494).
- Reports of AI-agent attacks against European financial firms (A0247).
- Spread of unrest to Germany affecting branches or staff safety (A0551, A0030).

## 3. Deliberately not acting on
- A1071 (Russian rule that banks reject transfers from infected phones): a Russian regulation, not EU/German, informational only. Possible idea for later product design.
- A1413 (Putin's cybersecurity meeting, 14 October): no content relevant to us. The headline concerns Belgian foreign ministry sites, but the text is unrelated to it.
- A0025, A0595, A0664, A1277 (Yandex, Steam, Avito and other outages): not our suppliers.
- A1313, A1900 (AfD policy commentary): political, no security effect.
- A0551 (riot commentary as a driver of decisions): opinion piece from a partisan outlet, used only as a weak input to item 6.
