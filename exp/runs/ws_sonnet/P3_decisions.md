# P3 General Counsel: whole-week decision memo (marketplace + own brands on WB/Ozon, personal data, advertising)

## 1. Key issues

1. **Platform-rule and seller-contract regulation is moving (A0443, A0768, A1035, A0293, A0586, A0853, A0597, A0594).**
   - Facts: The Union of E-commerce (Союз электронной торговли) complained to FAS and Minpromtorg about Ozon's new promo terms. Sellers lost the ability to cap discounted volume or exit promos, and FBO sellers are most exposed (A0443). The Marketplace Sellers Union (СПМ) asked the presidential administration, FAS and the Duma committee to amend the platform economy law. It wants fees split and made transparent, sellers free to choose the delivery method, and a ban on demoting sellers in search results (A0768). The Consumers Union and Rospotrebnadzor are criticising manipulative UX such as countdown timers and stock counters (A1035). Ozon is adding an agent fee for pickup-point owners from 1 Dec, citing the legal rule that agency services are paid (A0293).
   - Transmission: We run a marketplace, so we are the likely target of these amendments and complaints. Our promo mechanics, fee schedule, search ranking and delivery rules need to survive FAS scrutiny. We are also a seller on WB and Ozon, so we bear the same promo-term risk as an FBO seller.
   - Why now: Letters dated 15 and 16 October are with FAS and the Duma. The law is still open to amendment, so our lobbying window is open. Ozon is gaining share among large sellers (A0586, A0853), which raises our dependence on its terms.
2. **Dark patterns and advertising claims are drawing enforcement (A1035, A0182, A1187, A1261, A0442).**
   - Facts: FAS ruled MegaFon's "5G mode" advertising misleading and will consider administrative liability (A0182). Marketplace urgency tactics are under criticism (A1035). RWB warned of fake "written-off warehouse books" scams that impersonate the platform (A0442).
   - Transmission: The same theory (a claim that creates a false impression) can be applied to our "only N left" counters, timers, discount labels and own-brand claims. The scam and impersonation material adds a consumer-protection angle to our duty to police fake sellers.
3. **A PHP zero-day creates a personal-data incident window (A1730, A1902, A1507, A1449, A1495, A1460, A1803).**
   - Facts: Two critical remote-code-execution flaws were disclosed on 20 October, and exploitation was already reported. The patch was released about 16:45 MSK on 21 October. Governments and hospitals in the Netherlands, Finland and Germany took sites offline. Tens of thousands of Runet sites are at risk, including 1C-Bitrix and WordPress.
   - Transmission: Our storefront, admin and ad portals may run PHP and hold customer personal data. A breach brings Russian data-breach notification duties, regulator exposure and fines.
   - Why now: The patch window is hours to days, and there are reports of live attacks.
4. **Vendor and hosting concentration risk, plus a separate breach at a hosting-software vendor (A0478, A0025, A0262, A0581, A0595, A0421, A0185, A0691).**
   - Facts: VMmanager (Astra Group) was breached and several hosting providers reported it (A0478). Drone strikes on Yandex data centres (8-11 October) disrupted Yandex services and more than 10 tenant companies. Yandex Direct was down 11-14 October and is now restored (A0581, A0595, A0262). Arbitration-court hearings are being postponed because of the strikes (A0025). AKIT has asked for an emergency regime for trading during state-system outages (A0421). Avito (A0185) and Google Cloud London (A0691) had outages.
   - Transmission: This is a contract issue (SLA, force majeure, data-processing terms, sub-processors, exit rights) and a data-protection issue (whether the VMmanager breach touches our hosts). It is also an advertising-continuity issue, because our ad spend runs through Direct.
5. **Litigation environment and strategy (A0025, A0724, A1386, A1623, A1601).**
   - Facts: Hearings are being postponed, and the cause is explicitly cited in some court rulings (A0025). The Constitutional Court allows lawyers to collect fees from the losing side by assignment of the claim for costs (A0724). An Urals district cassation court upheld an ICC award and found no counter-sanctions circumvention through assignment of the claim (A1386). The Supreme Court is pushing higher compensation for unauthorised use of photos, including a logo applied without consent (A1601). AI-drafted lawsuits are rising (A1623).
   - Transmission: Case timelines slip, third-party legal funding and assignment structures become viable against us, and photo and IP exposure for seller listings goes up.
6. **Global privacy enforcement benchmark (A1979, A1913, A1825).**
   - Facts: A New Mexico court fined Meta $25bn for misleading users about privacy, after a jury found 43.9 million wilful violations. The statutory maximum was $219bn.
   - Transmission: There is no direct Russian effect. It is a board-level benchmark for privacy-notice accuracy and a useful frame for an internal audit of consent and disclosure wording. The Russian-law exposure is separate.
7. **Platform liability for illegal goods and fraud (A0367, A0442, A0762, A0773, A0788, A0164, A0186, A1276).**
   - Facts: France demanded immediate removal of looted-goods listings and cooperation with the authorities (A0367). Brand-impersonation scams earned fraudsters more than 1.1bn rubles, with retail the most imitated sector (A0762). MVD issued prepayment warnings (A0773, A0788). A deepfake of the defence minister is circulating (A1276).
   - Transmission: The pattern across these items is that regulators expect takedown speed and cooperation. We need a notice-and-takedown process, brand-abuse enforcement and fraud-reporting channels.
8. **1 November compliance and seller-tax changes (A1801, A0998, A1754, A1471, A0776).**
   - Facts: From 1 Nov the Chestny Znak marking list expands to vegetable oils, dairy and fertilisers, with UPD documents carrying marking codes (A1801). FNS's outstaffing experiment covers 35-40% of e-commerce (A0998). FNS is intensifying its "paper VAT" enforcement (A1754). Proposals to index the self-employed income limit are being discussed (A1471). Rospotrebnadzor fined Metro for missing labels (A0776).
   - Transmission: Marketing and seller-document requirements for newly marked categories, plus tax-risk clauses in seller and contractor contracts.

## 2. Decisions

1. **Launch a PHP incident response now (A1730, A1902, A1507, A1495, A1460).**
   - Direct IT/security today to confirm patching of every PHP system (storefront, seller cabinet, ads, CMS) and review logs from 20 October onward for exploitation.
   - Pre-draft the regulator and customer notification steps in case of compromise, with a 72-hour internal decision clock.
   - Requires combining: the flaw advisories, the VMmanager breach (A0478) and the hosting-provider list.
2. **Run a vendor and hosting contract review (A0478, A0025, A0262, A0581, A0691, A0185).**
   - This week: ask each hosting and cloud provider whether it uses VMmanager.
   - Within 30 days: review SLA, force majeure, data-processing and exit terms for the top hosting, ad and payment vendors. Add a continuity annex covering strike-related outages.
   - Requires combining: the outage items and the breach item.
3. **Audit our own consumer-facing claims against the FAS misleading-advertising standard (A0182, A1035, A1187, A1261).**
   - Review countdown timers, scarcity counters, discount-reference prices and own-brand claims, with sign-off from the legal function.
   - Remove or substantiate any claim we cannot support within 2-3 weeks.
4. **Prepare and file a lobbying position on the platform economy law (A0768, A0443, A0421, A0293).**
   - Offer constructive points on fee transparency and ranking rules, and support AKIT's emergency-regime proposal (A0421) as a continuity measure.
   - Engage through the industry associations in November, before the amendments are drafted.
   - Requires combining: the SPM and Union of E-commerce letters, plus Ozon's agency-fee reasoning.
5. **Pre-emptively review our seller and partner terms (A0443, A0768, A0293, A0586).**
   - Check promo opt-in/opt-out and discount-volume caps, ranking criteria disclosure, fee itemisation and delivery-method choice against the points complained about.
   - On the seller side, review our own-brand exposure to Ozon's promo terms and prepare a position if we are hit by the same mechanics.
6. **Stand up a notice-and-takedown and brand-protection process (A0367, A0442, A0762, A0773, A1601).**
   - Define response times for stolen-goods, counterfeit and scam listings, a law-enforcement liaison point and a seller KYC refresh.
   - Add a photo/IP infringement complaint procedure reflecting the Supreme Court position.
7. **Prepare for the 1 November changes (A1801, A0998, A1754).**
   - Update seller documentation requirements for newly marked categories before 1 November, and add tax-risk warranties to seller and contractor contracts.
   - If we use outsourced staff, review them against the FNS outstaffing experiment.
8. **Adjust litigation and contingency planning (A0025, A0724, A1386).**
   - Build in scheduling slippage for pending cases and check limitation periods.
   - Brief the team on assignment-of-costs risk when negotiating settlements.
   - Note the ICC-award precedent for any cross-border claims we hold.
9. **Send a short board note on the Meta ruling (A1979, A1913).** Recommend a privacy-notice and consent audit as a low-cost step.

## 3. Monitor

- Regulator actions on the Union of E-commerce complaint (FAS, Minpromtorg) and any FAS decision on MegaFon (A0443, A0182).
- Draft amendments to the platform economy law and Duma committee reaction (A0768).
- PHP exploitation in Russia, plus any further VMmanager victims (A1730, A0478).
- Further drone strikes on data centres and court-hearing delays (A0025, A0262).
- Ozon agency fee from 1 December and the spread of the same logic to other platform partners (A0293).
- Draft federal law on fines for non-compliance with regional operational-staff decisions, relevant to our content and advertising (A0405).
- Rising child-social-media restriction trend in Russia and Australia (A0637, A0466).
- Digital ruble payment acceptance (A0447); WB state-certificate payments (A0486); WB-VTB discounts (A0594).
- Temporary management of foreign-owned subsidiaries, if any counterparty is affected (A0019, A0041).
- Sanctions direction after Trump's statement (A1999).
- AI-agent governance incidents (A0775, A0820).

## 4. Traps

- **Meta $25bn fine (A1979, A1913, A1825):** It is a New Mexico state-law ruling against a company banned in Russia, so it does not set Russian law. Use it only as a risk benchmark. Do not reprice Russian exposure from it.
- **Foreign government site shutdowns (A1449, A1495, A1460, A1803):** Covered by the PHP decision. The shutdowns themselves do not require us to take our site offline. Patching is the response.
- **Music and copyright dispute (A0498, A0916):** Weak IP context, a celebrity feud with no bearing on our business.
- **Leaked stories on messenger usage (A0287), foreign brand openings (A0409), tax budget news (A0327), self-employed limit (A1471):** Background. No action is justified yet.
- **US DeepSeek ban (A0305), AI agents bypassing monitoring (A0775, A0820):** No clear link to our operations unless we use these tools. Check the AI-tool inventory, but do not drive decisions from these items.
- **Personal fraud stories (A0164, A0186):** Customer-advice material. Use it for consumer messaging only.
- **Labor Code 2027 (A0600), Metro labelling fine (A0776):** Not specific to our model. Include only in the routine compliance calendar.
- **Deepfake and French looting items (A1276, A0367):** Use for process design, not for urgent action.
- **Market-share items (A0586, A0853):** Commercial rather than legal, and WB disputes the analysis.

## 5. Ideal top-10

TOP10: ["A0768","A0443","A1730","A1902","A0478","A0182","A1035","A0293","A0025","A0421"]
