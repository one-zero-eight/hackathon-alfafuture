# Memo U14: CEO / owner, IT services (OKVED J), Moscow, small company, salary bank

## 1. Decisions now

1. **Assign an owner to the telecom and security rules that may affect our hosting.** Owner: CTO. Items: A1527 (Mintsifry set up a sector headquarters protecting key communications sites, with backup of nodes and trunk lines), A0884 (same headquarters, protecting sites from drone attacks). Path: our hosting providers may change network or site availability. Check: rule 4, is our region affected; Moscow is named in the items only as the ministry location, so ask user about our data centres.
2. **Check backup and continuity plans for cloud outages.** Owner: CTO. Items: A0691 (Google Cloud London outage hit European services, including Revolut), A0494 (Revolut global outage on 20 Oct). Path: an outage at a cloud or payment provider stops our services. Check: rule 4, direct exposure only if we use these providers; ask user.
3. **Review cybersecurity readiness after the PHP vulnerabilities.** Owner: CTO. Items: A1507 (two critical PHP vulnerabilities; European government sites taken offline), A1730 (threat to tens of thousands of Runet sites from a PHP flaw found with AI). Path: unpatched PHP code exposes our sites. Check: rule 4, applies if we run PHP; patch within the week.
4. **Test the bank-transfer device checks due 1 March 2027.** Owner: finance and IT. Items: A1071 (banks will reject transfers from devices with malware from 1 Mar, under law 210). Path: our payroll or vendor payments could be refused. Check: rule 5 for accountant; salary-bank exposure depends on our bank; ask user.
5. **Hold IT capex decisions until the telecom licensing reform is clear.** Owner: CEO. Items: A1633 (telecom licensing reform, capital and coverage requirements). Path: new licence rules may change our vendor choice. Check: rule 1, applicability is not stated.

## 2. Monitor

- **A1413 and A1495 (government site shutdowns in Europe):** if our clients ask for shutdown plans, prepare a communication.
- **A1242 (AI boom bubble risk):** if AI vendor pricing rises, revisit our procurement plan.
- **A0809 and A0305 (DeepSeek app rankings; US ban on Chinese AI services):** if our stack uses such models, review vendor risk.

## 3. Deliberately not acting on

- **A0936, A0334, A1517, A2000, A0715 (Starlink for Ukraine):** geopolitics with no stated effect on our business.
- **A1325 (Sheremetyevo baggage system):** import substitution news, no contract effect.
- **A0768 and A1035 (marketplace platform law and manipulation):** no direct tech or contract effect for us.
