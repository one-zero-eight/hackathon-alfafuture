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
