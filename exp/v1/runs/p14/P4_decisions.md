# CISO memo, week of 2026-10-21

## 1. Decisions now

1. **Patch the PHP estate.** By 2026-10-23, inventory every PHP runtime and web app (internal, partner, vendor-hosted). Patch internet-facing hosts to the fixed release by 2026-10-25, all others by 2026-10-29. If an exposed host cannot be patched by then, deploy a WAF virtual patch or disable the affected feature. Owner: Head of Infrastructure with AppSec. Items: A1449, A1507, A1495, A1803, A1671, A1674. Path: two critical PHP flaws; PHP maintainers urge immediate updates; German hospital and agency sites pulled offline. Direction check: exploitation is not confirmed, so no alert raise; the maintainer advisory plus our internet exposure sets the 24-72h timing instead of the 14-30 day cycle.

2. **Hunt for PHP exploitation.** By 2026-10-24, review web and WAF logs since 2026-10-15 on every internet-facing PHP host for exploitation indicators. Any hit opens an incident and triggers a compromise hunt. Owner: SOC. Items: A1449, A1803. Direction check: cheap log review; playbook cross-signal (a) applies only once exploitation is confirmed.

3. **Scan external attack surface and harden credentials.** External scan of all internet-facing assets by 2026-11-05; fix critical and high findings within 14 days. Enforce phishing-resistant MFA on admin and remote-access accounts by 2026-11-30. Owner: CISO with IAM. Items: A0247, A1025. Path: AI agents breached 100+ sites in about 23 hours at roughly $50; 56% of attack paths used valid credentials. Direction check: vendor report (NorForge), not sector-specific, so no alert raise.

4. **Run a state-actor tabletop.** By 2026-11-19, hold a tabletop on sabotage plus DDoS against a German bank. Share threat intelligence with BSI and the sector CERT; heighten monitoring of critical sites. Owner: CISO with physical security. Items: A0807, A0900. Path: Kremlin reportedly warned Germany the Leipzig sabotage attempt is not the last. Direction check: rule 8 applies; no campaign against banks is reported, so alert level stays.

5. **Brief executives and payment staff.** By 2026-10-30, targeted awareness brief for executives, treasury and payment operations. By 2026-11-13, simulated phishing using AI-written pretexts. Payment-detail changes or new beneficiaries above EUR 10,000 require callback to a number on file. Owner: Head of Fraud Prevention. Items: A0431. Path: 421k leaked emails with identity photos and AI-generated summaries. Direction check: the victim is a political party, not us; we act only on the transferable technique.

6. **Update the AI tool policy.** Within 14 days, publish an approved GenAI tools list; block unapproved tools, including DeepSeek, at proxy and DNS; prohibit customer data in public models; set access rules for AI agents. Owner: CISO with Data Protection Officer. Items: A0305, A0820. Direction check: the US federal order is informational only; the action rests on our rule 7.

7. **Check cloud region dependencies.** By 2026-10-31, list all services hosted in Google Cloud europe-west2 and confirm failover. Test one failover by 2026-11-14. Owner: Head of Infrastructure. Items: A0691, A0494. Direction check: an outage, not a compromise, so no supplier attestation under rule 4; this is an availability check.

## 2. Monitor

- A0551, A0030, A0246: unrest in France, Italy and Spain. Trigger: hacktivist DDoS claims naming German or EU banks, which raises alert level under rule 3.
- A1449 series: Trigger: confirmed exploitation of the PHP flaws (vendor or KEV listing). Then rule 1 applies to all exposed hosts, alert is raised, and a compromise hunt starts (cross-signal a).
- A0820, A0305: Trigger: vendor advisory for a GenAI tool we use or permit.
- A0807: Trigger: a second sabotage attempt on German infrastructure. Raise alert and brief SOC 24x7.

## 3. Deliberately not acting on

- A1071, A0186, A0788, A0773, A0762, A0442: Russian retail banking and consumer fraud rules and warnings. Outside EU/German regime and not our customers' channel.
- A0112: falling Russian DDoS counts. Irrelevant geography.
- A0664, A0025, A0595, A0843, A1105: strikes on Russian and Ukrainian infrastructure. No transmission path to us.
- A1979, A0541, A1260, A1242, A0299, A0141: generic tech news, fines and market commentary. Rule 12 applies.
- A1276: fake minister video. Disinformation, no action on our side.
