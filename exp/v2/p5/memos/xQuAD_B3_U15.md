# Memo U15: CEO / owner, OKVED J (software and IT services), Moscow, large company, salary

## 1. Decisions now

1. **Patch PHP on all public properties within 48 hours and confirm in writing to the CEO.** Items: A1507 (two critical PHP flaws, fixes released 20 Oct), A1730 (tens of thousands of Runet sites at risk). Owner: CISO. Check: applies only if our stack uses PHP; confirm the version now.
2. **Test a disaster recovery switch for the core platform by 30 Nov.** Items: A0494 (Revolut outage 20 Oct), A0691 (Google Cloud London failure), A0025 (attacks on Yandex data centres that disrupted court systems). Owner: CTO. Threshold: if the test misses our recovery target, add a second provider or region. Check: no outage in our own estate is reported; this is a test, not a fix.
3. **Ask the CFO to confirm cyber-insurance cover for outage and attack events by 15 Nov.** Items: A0025, A0494. Owner: CFO. Check: whether the current policy covers data-centre attacks; the cards do not show our policy terms.
4. **Run a fraud and phishing exercise across staff and key clients this quarter.** Items: A0164 (450 m rub taken in one Moscow case), A0762 (fraud revenue above 1.1 bn rub), A0502 (teen cybercrime up 30%). Owner: security lead. Check: rising threat per the cards.
5. **Map import-substitution tenders where our product fits.** Items: A1325 (domestic baggage system at Sheremetyevo), A0588 (import substitution for oil and gas equipment). Owner: CEO and sales. Check: no tender is named for us.

## 2. Monitor

- **A1633 and A0884 (telecom licensing and site protection).** Trigger: a telecom customer requests compliance or resilience work.
- **A1043, A1071 (bank device rules from 1 March).** Trigger: our product sends payments through bank apps.
- **A1406 (Moscow AI in medicine, 2027-29 budget).** Trigger: a tender in our scope.
- **A0025.** Trigger: our hosting provider reports attacks.

## 3. Deliberately not acting on

- **A0936, A0715, A0334, A1517, A2000, A1789 (Starlink and Starshield).** No effect on us.
- **A0305, A0809 (DeepSeek ban and ranking).** No export link.
- **A1242, A0831, A1825, A1979, A0917 (AI bubble, Anthropic loss, Meta and Netflix).** Market commentary.
- **A1413, A1507 cross-border items beyond our PHP stack.** Government site outages in Belgium and Germany are signals, not our decisions.
