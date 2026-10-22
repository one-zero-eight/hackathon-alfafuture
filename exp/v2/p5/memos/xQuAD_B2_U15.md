# Memo U15: CEO / owner, IT services (OKVED J), Moscow, large company, salary bank

## 1. Decisions now

1. **Assign an owner to the telecom licensing reform.** Owner: CEO / legal. Items: A1633 (Mintsifry reform: capital, network coverage and operating requirements for telecom operators). Path: stricter licences could raise costs for our telecom suppliers. Check: rule 1, applicability depends on whether our suppliers hold licences; ask user.
2. **Set up a continuity plan for a cloud outage.** Owner: CTO. Items: A0691 (Google Cloud London outage across European services), A0494 (Revolut global outage). Path: outages stop our services and payments. Check: rule 4, our exposure depends on our provider; ask user.
3. **Patch PHP-based sites this week.** Owner: CTO. Items: A1507 (two critical PHP vulnerabilities; governments taking sites offline), A1460 and A1674 (Netherlands, Finland and wider shutdowns). Path: exposed PHP code could be breached. Check: rule 4, applies if we run PHP.
4. **Plan for the 1 March 2027 bank device checks on salary and vendor payments.** Owner: finance. Items: A1071 (banks reject transfers from devices with malware from 1 Mar). Path: payroll transfers may be refused. Check: rule 5 for accountant; our bank choice is not in the items.
5. **Review physical and network resilience of our data centres.** Owner: CTO. Items: A1527 (sector headquarters for protecting key communications sites, with node and trunk-line redundancy), A0884 (protection against drone attacks). Path: attacks could take sites down. Check: rule 4, is our region affected; the items name Moscow only as the ministry location.

## 2. Monitor

- **A0809 (DeepSeek app rankings) and A0305 (US order to remove DeepSeek):** if our stack relies on these models, review vendor risk.
- **A1242 (AI bubble risk):** if AI vendor contracts reprice, revisit procurement.

## 3. Deliberately not acting on

- **A0936, A0334, A1517, A2000, A0715 (Starlink for Ukraine):** geopolitics with no stated business effect.
- **A1261 (marketplace browsing):** consumer news, no effect.
- **A0502 (teen cybercrime up 30%):** public-safety statistic; no direct action.
