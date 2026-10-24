"""Build one profile's page. Usage: python -m reasoning.run U01 [ROLE] [--sphere TEXT] [--no-triz]"""
import sys

from reasoning.chain import OUT, run
from reasoning.llm import LLM
from reasoning.view import html, tree


def main() -> None:
    argv = [a for a in sys.argv[1:] if a != "--no-triz"]
    sphere = ""
    if "--sphere" in argv:
        i = argv.index("--sphere")
        sphere = " ".join(argv[i + 1:])
        argv = argv[:i]
    pid = argv[0]
    role = argv[1] if len(argv) > 1 else "CFO"
    triz = "--no-triz" not in sys.argv
    OUT.mkdir(exist_ok=True)
    page = run(pid, LLM(OUT / "calls.jsonl"), triz=triz, role_name=role, sphere=sphere)
    (OUT / f"{pid}.html").write_text(html(page), encoding="utf-8")
    print(tree(page))
    print(pid, "widgets", len(page["widgets"]), "links", len(page["links"]), "->", OUT / f"{pid}.json")
    print("chain", OUT / f"{pid}.html")


if __name__ == "__main__":
    main()
