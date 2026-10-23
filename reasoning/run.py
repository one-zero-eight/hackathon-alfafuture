"""Build one profile's page. Usage: python -m reasoning.run U01 [--no-triz]"""
import sys

from reasoning.chain import OUT, run
from reasoning.llm import LLM


def main() -> None:
    pid = sys.argv[1]
    triz = "--no-triz" not in sys.argv
    OUT.mkdir(exist_ok=True)
    page = run(pid, LLM(OUT / "calls.jsonl"), triz=triz)
    print(pid, "widgets", len(page["widgets"]), "links", len(page["links"]), "->", OUT / f"{pid}.json")


if __name__ == "__main__":
    main()
