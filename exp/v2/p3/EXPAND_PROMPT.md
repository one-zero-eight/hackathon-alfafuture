A user logged into a business-news service. You know ONLY these login parameters:
{PROFILE}

Vocabulary (use only these values for tags): {VOCAB}

Produce ONE JSON object and write it to {OUT}, nothing else:
{"id": "<profile id>",
 "needs": [~20 Russian sentences, each one concrete information need of this role at such a company: which external events would change their decisions, via what path (costs, demand, credit, FX, tax, compliance, regional risks)],
 "hyde_cards": [~15 example event cards that would matter to this user, same schema as news cards: {"event": "<Russian sentence>", "okved": [...], "region": [...], "event_type": "...", "mechanism": "<Russian sentence>", "cause_effect": [{"okved": "...", "effect": "..."}]}],
 "aspects": [5-8 objects {"name": "<short Russian label>", "weight": <0-1, sum 1>, "needs": [indices into needs]}]}
Do not invent concrete facts or news; these are hypothetical needs. Reply "done".
