# CISO memo: news digest, 19-21 October 2026

## 1. Decisions now

1. **PHP exposure sweep, within 24h.** Inventory every PHP runtime and application, internet-facing and internal (owner: IT Operations, with CISO office). Ask CERT-Bund/BSI whether the two PHP flaws are confirmed exploited. If exploited and we run exposed PHP: WAF virtual patch now, patch within 24-72h, and hunt for compromise (cross-signal a). If not exploited: standard 14-30 day cycle. Items: A1449, A1674, A1507, A1495, A1803, A1460, A1671, A1413. Path: German clinics and government sites were taken offline over PHP flaws. Check: the items do not say the flaws are exploited, so severity alone does not raise the alert level (rule 2).

2. **External attack-surface scan, within 2 weeks.** Scan all internet-facing hosts and applications; remediate high findings within 7 days (owner: security testing). Items: A0247, A1025. Path: AI agents breached over 100 sites at about $50 each, and automated pentests reached data in 60% of companies. Check: the campaign hit the US, Canada, Australia and Japan, so we act on exposure, not geography.

3. **Authentication hardening, within 2 weeks.** Verify phishing-resistant MFA for staff, admin and online-banking login; test authentication redirect and OAuth paths (owner: IAM lead). Items: A1025. Path: 9 of 10 attack paths used valid credentials or authentication flows. Check: this is one vendor's test result, so we verify our own configuration rather than assume it.

4. **Unapproved AI-tool check, within 1 week.** Search proxy and expense data for DeepSeek and similar services; block unapproved ones and confirm no customer data goes to public models (owner: CISO with data protection officer). Items: A0305, A0247. Path: rule 7. Check: the US order binds US federal agencies only, so we act on our own AI policy.

5. **Targeted awareness, within 1 week.** Brief staff and run a simulated phishing round on pretexts built from leaked correspondence and identity documents; reinforce callback verification for payment-detail changes (owner: security awareness). Items: A0431. Path: 421k emails and ID photos from a German party were published. Check: a single hack-and-leak against a political party, not a wave, so awareness only, no alert change.

6. **Supplier concentration check, within 1 week.** Confirm whether any critical or DORA-relevant service depends on Google Cloud europe-west2 (London) and whether failover works (owner: vendor risk). Items: A0691, A0494. Path: a London data-centre failure disrupted Revolut and other European services. Check: no compromise is reported, so rule 4 does not apply; the DORA clock runs only if our services were affected.

7. **SOC briefing, this week.** Brief the 24x7 SOC on PHP exploitation and AI-agent scanning patterns and increase web-application logging. Items: A1449, A0247. Path: cheap, reversible visibility gain. Check: logging only, no change to alert level.

## 2. Monitor

- **PHP exploitation confirmed or listed as exploited (A1449, A1674):** if confirmed and we run the software, move to decision 1 emergency path.
- **AfD leak follow-up (A0431):** if published data shows bank-related or deepfake voice/video fraud against finance staff, trigger rule 6 response.
- **Google Cloud root-cause report (A0691):** if the cause is a security incident or our services were affected, open DORA major-incident classification.
- **European unrest (A0551; related A0030, A0050):** if cyber claims or hacktivist campaigns against European banks appear, trigger rule 8 tabletop within 2-4 weeks.
- **Belgian MFA shutdown (A1413):** sourcing is weak, since the card text concerns a Putin statement; confirm before acting.

## 3. Deliberately not acting on

- **A1071 Russian bank rule on infected phones:** Russian federal law, not EU or German regime (rule 5 check).
- **A0551 unrest, A0030, A0050:** physical disorder with no cyber link in the items.
- **A0025, A0664, A0595 (Yandex attacks and recovery), A1866, A0185, A1277 (Wikipedia, Avito, Steam outages):** no link to our systems; generic news (rule 12).
- **A0809 AI-danger commentary:** speculative, no exposure.
