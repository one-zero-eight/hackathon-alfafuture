# CISO memo: news digest, week of 2026-10-21

## 1. Decisions now

1. **PHP exposure sweep.** Within 48h, inventory all PHP runtimes and applications (owner: Head of AppSec) and flag internet-facing ones. Patch to the vendor-fixed release within 7 days; if that is not possible, deploy WAF virtual-patch rules within 72h. Items: A1671, A1449, A1803, A1495, A1730. Transmission: German state sites went offline over critical PHP flaws, so our public PHP apps may share them. Direction check: no exploitation is reported, so rule 2 governs (no alert raise), but exposed PHP justifies a faster-than-standard 7-day window because the cost is low.

2. **Hold alert level; pre-define the trigger.** Keep the current level. If a PHP CVE appears on CISA KEV or a vendor emergency advisory, switch to rule 1: patch internet-facing instances in 24-72h and hunt for compromise. Items: A1671, A1803. Direction check: the items describe a precaution, not confirmed attacks against banks.

3. **Reduce automated-exploitation exposure.** Within 2 weeks, review the internet-facing asset list, enable rate limiting and bot management on online-banking login and API endpoints, and confirm WAF blocking of known exploit patterns (owner: SOC lead). Items: A0247 with decision 1. Transmission: AI agents breached 100+ sites in about 23 hours each at roughly $50, so cheap automated scanning lowers the attacker's cost. Direction check: targets were in the US, Canada, Australia and Japan; no German target is reported, so only cheap controls, no alert change (rule 12).

4. **Block unapproved AI tools, including DeepSeek.** Within 1 week, search proxy and endpoint logs for DeepSeek and other unapproved AI services, block them, and restate the rule that no customer data goes into public models (owner: CISO office). Items: A0305, A0247. Rule 7. Direction check: the US federal procurement ban is informational only; our driver is data-leak risk, not US law.

5. **Cloud concentration review.** Within 48h, request a root-cause report from Google Cloud on the London (europe-west2) outage under the DORA third-party register, and confirm which of our ICT services depend on that region. Test failover within 4 weeks. Items: A0691, A0494. Transmission: the outage disrupted Revolut and other European services. Direction check: this was an outage, not a compromise, so rule 4 attestation does not apply; we request an RCA only.

6. **Awareness on leaked correspondence.** Within 2 weeks, issue a targeted reminder on payment callback procedures to staff in payments and treasury. Item: A0431. Transmission: 421k leaked emails with AI-generated summaries create material for convincing lures. Direction check: no link to our bank is reported, so awareness only, no simulated phishing.

## 2. Monitor

- **A1671, A1803:** if a PHP CVE is listed as exploited, or our scan finds exposed PHP, apply decision 2.
- **A0247:** if automated exploit traffic hits our assets or a German peer reports a breach, apply rule 9: check IOCs and test incident response.
- **A1449, A1460:** if a DDoS or ransomware campaign targets German banks, apply rule 3 (raise alert, verify backups, brief SOC 24x7).
- **A0431:** if our staff names or data appear in the leak, or a lure cites its contents, apply rule 6.

## 3. Deliberately not acting on

- **A1071, A1043:** Russian central bank rules from 1 March. Not our regime.
- **A0299, A0141, A0219, A0809:** AI risk speculation with no operational link to our systems.
- **A1277, A1866:** Steam and Wikipedia outages, unrelated to our services.
- **A0679:** AI in Russian science, no transmission to us.
