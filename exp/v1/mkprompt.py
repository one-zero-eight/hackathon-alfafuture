import json, os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
per = json.load(open(os.path.join(ROOT, "personas.json")))
tpl = open(os.path.join(ROOT, "DECIDE_PROMPT.md")).read()
v = sys.argv[1]
for p, x in per.items():
    news = open(os.path.join(ROOT, "runs", v, f"{p}_news.txt")).read()
    open(os.path.join(ROOT, "runs", v, f"{p}_prompt.md"), "w").write(
        tpl.replace("{ROLE}", x["role"]).replace("{COMPANY}", x["company"]).replace("{AUTHORITY}", x["authority"]).replace("{NEWS}", news))
print(v, "prompts ok")
