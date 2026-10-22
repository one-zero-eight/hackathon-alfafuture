PASS 1 - digest
[A1413] Belgian foreign ministry shut its websites over cyber threat; Putin stresses digital security (14 Oct). Lever: security posture (indirect).
[A0494] Revolut global outage on 20 Oct; company says funds safe. Lever: vendor continuity (indirect).
[A0691] Google Cloud London data-centre outage hit European services including Revolut. Lever: cloud dependency (direct).
[A1277] Steam outage reports on 21 Oct. Lever: none.
[A1633] Telecom licensing reform with capital and coverage rules. Lever: none direct.
[A1527] Ministry of Digital Development set up a staff to protect communication networks; backup of nodes. Lever: none direct.
[A0884] Ministry set up a staff to protect communication sites from drones. Lever: none direct.
[A1242] AI bubble may burst from closed funding loops (analyst view). Lever: none direct (strategy watch).
[A1507] Critical PHP vulnerabilities; government and public sites in Europe taken offline. Lever: our stack patching (direct if we run PHP).
[A1460] Netherlands and Finland took government sites offline over PHP risk. Lever: patching (direct if PHP).
[A1674] More government sites worldwide taken offline over PHP. Lever: patching (direct if PHP).
[A1449] Germany took hospital and agency sites offline over PHP risk. Lever: patching (direct if PHP).
[A1730] Tens of thousands of Runet sites exposed to an AI-found PHP flaw. Lever: patching (direct if PHP).
[A0936] Musk slowed Starshield for Ukraine (WSJ). Lever: none direct.
[A1325] Sheremetyevo replaced foreign baggage software with a domestic system. Lever: import substitution (indirect).
[A0768] Marketplace sellers ask to change platform economy law. Lever: none direct.
[A1071] Banks to reject transfers from infected devices from 1 March. Lever: product compliance (direct).
[A0809] DeepSeek app tops charts; market worry. Lever: model choice (direct if we use it).
[A0305] US agencies ordered to remove DeepSeek products. Lever: model choice (direct if we use it).
[A0662] Crypto exchange Mexc ends service to Russia and Belarus. Lever: none direct.
[A0478] Group Astra shares fell about 4% after a hacking news story. Lever: vendor screening (direct if we use Astra).
[A0588] Deputy PMs discuss import substitution of oil and gas equipment. Lever: procurement (indirect).
[A1979] Meta fined $25bn for misleading users on data protection. Lever: privacy practice review (indirect).

=== MEMO ===
Memo: security and patching, vendor screening, payment compliance and model choice. Company: CEO, small software and IT services (OKVED J), Moscow, salary bank product.

1. Decisions now

1) Confirm whether our production stack runs PHP; if yes, patch to the fixed version within 48 hours and log the action. Owner: CTO. Items: A1507, A1460, A1730. Path: critical PHP flaws are public and widely exploited. Check: our stack is not stated; one-line check, no action if we do not use PHP.

2) Screen any vendor under current security news (Group Astra) before renewing contracts; pause new orders until screened. Owner: Procurement. Items: A0478. Path: a hacking story hit the vendor, a counterparty risk signal. Check: whether we use Astra is not stated; act only if we do.

3) Confirm customer payments survive transfers refused from infected devices from 1 March, and test a fallback provider. Owner: IT. Items: A1071, A0494. Path: bank rules may block payments; outages happen. Check: whether customers pay through bank apps is not stated.

4) If we use DeepSeek or another Chinese model, review the US ban and our data-use terms within two weeks. Owner: CTO. Items: A0305, A0809. Path: a US ban can affect partners, and popularity can change terms. Check: whether we use the model is not stated.

5) List critical services hosted in one cloud region and add a second region for them. Owner: CTO. Items: A0691. Path: a single-region outage took down European services. Check: our cloud setup is not stated.

2. Monitor

- A1507, A1730: PHP patches and takedowns. Trigger: confirmed attack on a Runet site using PHP, then review decision 1.
- A0588, A1325: import substitution. Trigger: procurement mandate for our systems, then plan a switch.
- A1979: privacy fines. Trigger: any change in our data-use terms that needs review.

3. Deliberately not acting on

- A0936, A1413, A0884, A1527: Starlink, Belgian sites, drone protection, network staff. Reason: government or foreign operations, no direct lever.
- A1242, A0662, A1277: AI bubble view, crypto exchange exit, Steam outage. Reason: no effect on our business.
- A0768: marketplace platform law. Reason: not our sector.

Ponytail closing: skipped a dependency audit (no stack data). Risk: decisions 1, 4 and 5 depend on our stack, which is unstated; decision 2 depends on whether we use Astra.
