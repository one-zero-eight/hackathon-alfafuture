# CISO memo: week of 19-21 Oct 2026

Themes: (1) PHP critical-vulnerability wave, (2) AI-automated attacks on exposed sites, (3) leaked and AI-written social engineering, (4) cloud concentration risk, (5) AI-tool policy, (6) low-relevance AI and foreign-regulation items.

## 1. Decisions now

1. **Emergency PHP sweep (within 24h).** IT Operations inventories every PHP instance on internet-facing systems, including vendor-hosted and third-party ones, and reports to me. Patch to the vendor's fixed version within 48h. Anything not patchable within 72h is taken offline or shielded by WAF virtual patching. Owner: Head of IT Operations; CISO signs off. Items: A1671, A1803, A1449, A1460, A1674, A1507. Path: remote code execution on public servers leads to data breach, outage, and BaFin/KRITIS reporting.
2. **Elevated alert level for web-facing systems, 14 days.** Review on day 14 and lower it only if the sweep finds no vulnerable instance. Owner: CISO. Items: A1671, A1803.
3. **Shorter patch SLA for external assets.** Critical patches on internet-facing assets within 72h, and a weekly external attack-surface scan. Owner: CISO with Vulnerability Management. Items: A0247, A1507. Path: a reported AI-agent campaign hit more than 1,200 sites at about $50 per successful break-in, so cheap mass exploitation of mid-sized exposed sites is plausible.
4. **Staff awareness module within 10 working days.** Cover AI-written lures, leaked-mailbox content used as pretext, and call-back verification for payment changes. Owner: Security Awareness lead. Items: A0431, A0247. Path: leaked staff mail plus AI-generated lures lead to credential phishing and payment fraud.
5. **Breach-monitoring check of our domain.** Check for our staff mailboxes in public dumps, and force resets on any hits. Owner: SOC. Items: A0431.
6. **Cloud provider post-mortem request within 10 working days.** Ask Google Cloud and other critical providers for root-cause reports on the 20 Oct London/europe-west2 outage. Confirm which of our services run in that region and whether failover exists. Owner: Third-Party Risk Manager. Items: A0691, A0494.
7. **AI-tool inventory within 2 weeks.** Identify all AI services in use. Block unapproved ones that touch customer or internal data at the proxy. Owner: CISO with IT. Items: A0305.

## 2. Monitor

- **PHP exploitation in our stack.** Trigger: a BSI or vendor advisory names active exploitation, or the sweep finds a vulnerable instance we cannot patch in 72h. Then isolate immediately. Items: A1507, A1730.
- **AI-agent attack campaigns against our sector.** Trigger: a campaign reported against German banks, or more than 5 critical findings in the weekly external scan. Then escalate to the board. Items: A0247.
- **Cloud concentration.** Trigger: a production dependency on one region without failover, or an outage longer than our RTO. Items: A0691, A0494.
- **Chinese-model AI services.** Trigger: the inventory finds use with customer data, or a German or EU authority issues a similar notice. Items: A0305.

## 3. Deliberately not acting on

- **A0299, A0141, A0219, A0809 (AI "existential risk" and superintelligence pieces).** Opinion and speculation. The 10% and 2100 figures are not measurable for our risk register. The Anthropic claim about TV-borne bots is a vendor statement with no detail.
- **A0305 as a blanket ban.** The US order binds US civilian agencies, not us. Item 7 covers the real exposure.
- **A1071, A1043 (Russian bank rules on infected phones).** Different legal regime. Our mobile app's malware checks are reviewed under our normal process.
- **A1277, A1866 (Steam and Wikipedia outages).** No link to our services.
- **A0494 as an own-bank event.** Revolut is a UK fintech; it matters only as evidence for item 6.
