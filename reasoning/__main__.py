"""python -m reasoning U01            build the page for one profile
python -m reasoning U01 --no-triz   same chain without TRIZ moves
python -m reasoning --alfa          parse PDFs from external-docs/alfa into reasoning/out/alfa-theses.jsonl
"""
import sys

from reasoning.llm import LLM


def main(argv: list[str]) -> None:
    if "--alfa" in argv:
        from reasoning.alfa import parse_dir
        found = parse_dir(LLM(log_path=__import__("pathlib").Path("reasoning/out/calls.jsonl")))
        print(f"theses {len(found)}")
        return
    pid = next(a for a in argv[1:] if not a.startswith("--"))
    from reasoning.chain import OUT, run
    from reasoning.evaluate import score
    from reasoning.data import corpus
    page = run(pid, LLM(log_path=OUT / "calls.jsonl"), triz="--no-triz" not in argv)
    _, items = corpus(pid)
    print(score(page, items, pid))


if __name__ == "__main__":
    main(sys.argv)
