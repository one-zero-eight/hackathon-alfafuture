{sphere_line}
{facts_line}
Роль: {role_title}. Полномочия: {role_authority}.
Правила роли:
{role_playbook}
Приёмы (выбирай только из списка):
{moves}
Новость: {title}
Аналитика: {notes}
Дай одно решение для этой компании по этой новости. Оно обязано ссылаться на аналитику. Привязка к компании — здесь, не в аналитике. Приём ТРИЗ — только если его нет среди правил роли.
horizon — срок самого действия, с причиной в why: urgent (до месяца), medium_term (до года), not_urgent (дольше года). Не ставь medium_term, если из новости следует другой срок.
type: risk, opportunity или observation.
probability и impact — целые 1..4 и разные по смыслу риска, не все 2 и 3. risks — от 2 до 4.
Первый символ ответа — {. Без текста вокруг.
{"title": "...", "text": "...", "why": "...", "horizon": "urgent", "type": "risk", "move": null, "contradiction": null, "risks": [{"name": "...", "probability": 2, "impact": 4, "mitigation": "..."}]}
