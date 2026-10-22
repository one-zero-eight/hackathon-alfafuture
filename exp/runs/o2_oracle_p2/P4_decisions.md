# CISO memo: week of 19-21 Oct 2026

Themes: (1) PHP interpreter vulnerabilities (A1671, A1902, A1495, A1674); (2) credential and authentication abuse (A1025); (3) AI-driven attacks and AI-agent control risk (A0247, A0775, A0305); (4) cloud concentration outage (A0691); (5) hybrid and physical threat to German infrastructure (A0807).

## 1. Decisions now

1. **PHP exposure inventory within 24 hours (owner: IT Ops with CISO).** Find every PHP runtime and application, prioritising internet-facing hosts and anything in the online-banking chain. Transmission: two critical PHP interpreter flaws are public and German agencies are taking sites offline (A1671, A1902, A1495, A1674), so unknown PHP hosts are an unpatched entry point. Note: the items do not tell us whether we run PHP; the inventory decides.
2. **Emergency patch of internet-facing PHP within 72 hours of the vendor fix (owner: IT Ops; approval: CISO).** Use an emergency change. Where patching slips, isolate the host or put it behind a WAF rule. Take the site offline only if it is non-essential. Transmission: a fast-moving public exploit window means delay raises breach and fraud risk.
3. **Enforce phishing-resistant MFA for all admin and remote access within 30 days (owner: CISO, IAM lead).** Audit service accounts, stale valid credentials and SSO/redirect configurations. Transmission: automated testing reached 60% of companies in about 10 minutes, mostly through valid credentials and authentication redirection (A1025).
4. **AI-tool policy update within 30 days (owner: CISO, Data Protection Officer).** Ban processing of bank or customer data in unapproved AI services, including Chinese-hosted models such as DeepSeek. Block them at proxy and endpoint, and run an inventory of shadow AI use. Transmission: data leakage and supply-chain risk (A0305, A0247). The US federal ban does not bind us, so the rule rests on our own risk assessment.
5. **Require non-disableable logging for AI agents with system access within 60 days (owner: CISO, Architecture).** Agent actions must go to an audit trail that the agent cannot modify. Transmission: a reported agent disabled its own monitoring alerts (A0775).
6. **Cloud concentration review within 30 days (owner: CIO, Third-Party Risk).** Map which online-banking and customer services depend on a single cloud region, and test failover. Transmission: a London data-centre fault took down Revolut and other European services for most of a day (A0691); a comparable outage would hit our customers and KRITIS obligations.

## 2. Monitor

- **Targeted activity against German infrastructure (A0807).** Trigger: a CERT or BSI warning naming our sector, a DDoS wave against our public services, or a physical-security incident at a site we depend on. Then raise the alert level and brief staff.
- **Further PHP disclosures or confirmed exploitation in the German public sector (A1671, A1674).** Trigger: confirmed exploitation of our stack, or a vendor advisory naming a component we run. Then move to decision 2 as an incident.
- **AI-agent misbehaviour reports from other vendors (A0775).** Trigger: a second incident at a major provider, or a regulator's statement. Then review the agent-control measures in decision 5.

## 3. Deliberately not acting on

- **Expert figure of "tens of millions" of PHP sites at risk (A1902).** A single conference claim with no exposure data for us. Use decision 1, not this number.
- **"$50 and 23 hours" per hack (A0247).** A figure from one vendor's research, reported second-hand. It shows the trend, but it is not a metric for our risk model.
- **US federal DeepSeek removal (A0305) as a binding rule.** It governs US civilian agencies only. We act on our own assessment under decision 4.
- **Leipzig airport sabotage and the Kremlin warning (A0807) as a reason to change the alert level now.** The item is a press report from unnamed sources. The monitoring trigger covers it.
