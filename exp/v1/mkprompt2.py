import json, os, sys
ROOT = os.path.dirname(os.path.abspath(__file__)); v, tplname = sys.argv[1], sys.argv[2]
PB = json.load(open(os.path.join(ROOT, "playbooks.json"))) if os.path.exists(os.path.join(ROOT, "playbooks.json")) else {}
per = json.load(open(os.path.join(ROOT, "personas.json"))); tpl = open(os.path.join(ROOT, tplname)).read()
for p, x in per.items():
    news = open(os.path.join(ROOT, "runs", v, f"{p}_news.txt")).read()
    open(os.path.join(ROOT, "runs", v, f"{p}_prompt.md"), "w").write(tpl.replace("{ROLE}", x["role"]).replace("{COMPANY}", x["company"]).replace("{AUTHORITY}", x["authority"]).replace("{NEWS}", news).replace("{PLAYBOOK}", PB.get(p, "")))
print(v, "prompts ok")
