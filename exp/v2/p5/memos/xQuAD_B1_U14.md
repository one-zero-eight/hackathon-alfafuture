# Memo U14: CEO / owner, OKVED J (software development and IT), Moscow, small company, bank product salary

## Themes
- Software security: critical PHP vulnerabilities, with European government sites taken offline as a precaution (A1507); Belgian ministry shuts sites after cyber threat (A1413); Putin calls for digital-security priority (A1413).
- Network resilience: Ministry of Digital Development protects communication networks and reserves nodes (A1527); licence reform raising capital and coverage requirements for telecom operators (A1633).
- Banking security: from 1 Mar, banks must check devices for malware (A1071).
- Outage: Revolut global service outage on 20 Oct (A0494).
- Satellite dependency: Starshield slowed for Ukrainian users (A0936).
- Domestic systems: Sheremetyevo replaces baggage software with a domestic system (A1325).
- Market context: AI bubble risk (A1242); marketplace platform-law request (A0768), not an IT item.

## 1. Decisions now
1. **Check every PHP component and patch to the fixed release now.** Owner: CTO. Item: A1507. Path: the two critical PHP vulnerabilities can be exploited if left unpatched. Check: whether the company uses PHP; the packet does not say. If it does, patch this week.
2. **Assign an owner and a plan for the 1 Mar banking malware-check rule if our products sit in banking flows.** Owner: product lead. Item: A1071. Check: applicability, which the packet does not state.
3. **Review backup and restore tests against the outage pattern and the network-protection push.** Owner: CTO. Items: A0494, A1527. Path: rule 4 asks for continuity checks. Check: whether the company depends on a single external service; the packet does not say.
4. **Build a short resilience and cyber offer for telecom and government clients.** Owner: sales. Items: A1527, A1413, A1633. Path: network protection and licence reform raise demand for resilience work. Check: whether our clients are operators with capex; the packet does not say. Direction is mixed, since small operators may cut spending (A1633).
5. **Confirm we do not depend on a satellite-link provider affected by the Starshield slowdown.** Owner: CTO. Item: A0936. Check: the packet does not show a dependency.
6. **Check whether any client is in the domestic-software procurement wave.** Owner: sales. Item: A1325. Check: direction on our customers; no client list in the packet.

## 2. Monitor
- AI bubble view (A1242): if our sales pipeline depends on AI-funded clients, re-check hiring.
- Licence reform text (A1633): when the capital thresholds are published, re-check telecom clients.
- Revolut outage (A0494): if the company uses that service, check incident cost.

## 3. Deliberately not acting on
- A0768 (marketplace platform law): not a software decision.
- A0494 as a counterparty item: no evidence the company trades with Revolut.
