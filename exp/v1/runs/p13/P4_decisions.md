# CISO memo: news scan, week of 2026-10-21

## 1. Decisions now

1. **PHP exposure sweep.** Within 24h, inventory every PHP runtime and PHP-based site or CMS on internet-facing assets (owner: Head of Vulnerability Management). Patch any hit within 72h and deploy WAF rules against PHP code-execution patterns until patched. Driving items: A1449, A1671, A1460, A1674, A1507, A1495, A1803, A1413.
   Path: German hospital and government sites were taken offline over two critical PHP flaws; our exposure is unknown.
   Check: items describe critical flaws and precautionary shutdowns, not confirmed exploitation, so rule 2 (14-30 days) applies. I shorten it to 72h only for internet-facing assets. No alert raise.

2. **Compromise hunt on any hit.** If step 1 finds a vulnerable PHP asset that was reachable during the disclosure window, hunt web and WAF logs for code-execution indicators within 48h, and brief the SOC.
   Check: conditional on exposure, so it stays cheap and does not raise the alert level by itself.

3. **Faster external scanning and bot defence.** Move external attack-surface scans of internet-facing assets to weekly and enable rate limiting and bot detection on login and API endpoints within 2 weeks (owner: Head of Network Security). Driving items: A0247.
   Path: an AI agent breached over 100 sites in about 23 hours for roughly $50, so mass scanning is cheap.
   Check: a capability trend, not a new vulnerability in our software. The action is reversible.

4. **Identity hardening.** Within 7 days, run credential-exposure checks on staff and customer accounts. Within 30 days, enforce phishing-resistant MFA for privileged and remote access, and review authentication redirect flows in online banking (owner: CIO with CISO). Driving items: A1025, A0431.
   Path: in the pentest, 9 of 10 attack paths used valid credentials or authentication redirection.
   Check: the pentest is a third-party test, not our breach data, so this is a control review, not an incident.

5. **Phishing and deepfake controls.** Within 2 weeks, run a simulated phishing campaign and require payment callback verification for all payment-release staff and executive instructions. Driving items: A0431, A1025 (cross-signal d).
   Path: leaked mail from a German party, including ID photos and AI-generated summaries, is ready material for social engineering.
   Check: the leak targets a German political party, not a bank. We act because the same method applies to our staff.

6. **AI tool block.** Within 2 weeks, block DeepSeek and other unapproved Chinese-hosted AI services at proxy and DNS, confirm no customer data goes to public models, and update the approved-tools list (owner: CISO with Data Protection Officer). Driving items: A0305, A0809.
   Check: the US federal order is informational only. Our decision rests on our AI policy (rule 7), not on US law.

7. **Cloud concentration check.** Within 7 days, map which services depend on Google Cloud europe-west2 and test failover for the most critical one. Log the dependency in the DORA third-party register (owner: Head of IT Operations). Driving items: A0691, A0494.
   Path: a London data-centre fault disrupted European services, including Revolut.
   Check: an outage, not a compromise, and no bank service is confirmed affected. No incident report or alert raise unless our services were hit.

## 2. Monitor

- **Vendor or CISA exploitation of the PHP flaws** (A1449, A1674): if confirmed, switch to rule 1 (patch internet-facing within 24-72h) and hunt for compromise.
- **Hacktivist DDoS on German banks** (A1413, A0551 region): if claimed against German financial institutions, apply rule 3 (alert raise, DDoS check, SOC brief).
- **Leaked AfD data used against our staff** (A0431): if our staff or customers appear in the dump, or it is used in phishing, escalate to decision 5 immediately.
- **Repeat GCP europe-west2 outage** (A0691): if it lasts over 4h or recurs within 30 days, review contract and exit options.

## 3. Deliberately not acting on

- **Russian bank and police rules** (A1071, A1043, A1661, A0186, A0788, A0773, A0559): Russian regime. EU and German rules govern (rule 5).
- **French, Italian, Belgian and Spanish riots** (A0551, A0030, A0137, A1597, A0050, A1369, A0246): unrest, not a cyber threat to us. No link to our systems.
- **Yandex, Avito, Wikipedia, Steam outages** (A0664, A0025, A0595, A0185, A1866, A1277): not our providers. No exposure.
- **Russian cybersecurity meeting** (A1413 body): body describes a Russian meeting under a Belgian headline. Not a decision driver.
- **AfD policy papers** (A1313, A1900): political content, no cyber transmission.
- **Peer fintech outage** (A0494): an availability event, not a breach. Covered by decision 7.
