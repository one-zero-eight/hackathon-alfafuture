# AGENTS.md — Alfa Hack: News Analytics

Read this before working. Dialogue with the user is in English unless asked otherwise; code and comments are in English; commit messages, PR texts, `docs/`, section READMEs and `CHANGELOG.md` are in Russian.

**Case**: "News analytics for business decisions" (Alfa-Bank). An agentic system collects news, picks it for a specific business user, and explains what it means for their decisions (conclusions, risks, follow-up questions) with traceable reasoning. Hard constraints: only organizer-approved LLMs (Gemma 4 26B A4B, GLM-5.3-Flash, Qwen3.6 35B A3B, DeepSeek-V4.1-Flash, Qwen3-VL-30B-A3B-Instruct, Kimi-K2.6), budget 500 ₽/day; every conclusion traceable to its sources; native bank-product advertising in the output is allowed.

---

## 1. Project structure

```
collector/     Go. RSS + Google News -> Postgres; tags and regional geotags (Gemma). sources.json, topics.txt
agents/        Python, FastAPI. Every Python LLM call: 9 named agents, prompts/*.md
news_search/   Python. Class NewsSearch (lexical | dense_llm | dense_xquad), embedders, HyDE, dedup; HTTP wrapper
analytics/     Python, FastAPI. News -> analytics -> decisions with evidence; Alfa PDF theses; data/roles.json
backend/       Python, FastAPI. Orchestration, profiles/pages in Postgres, UI API, chat; config NEWS_SEARCH_METHOD
frontend/      TypeScript, React, Vite. The UI
docker/        All Dockerfiles, compose.yaml, nginx.conf, check.sh
docs/          One Russian doc per section + architecture.md + benchmark-template.md
external-docs/ Case brief, meeting notes, organizer data (company CSVs, Alfa PDFs)
```

Each section folder has `README.md` (files, run, tests), `benchmarks/` where measurements exist, and its doc in `docs/<section>.md`. Root: `pyproject.toml` + `uv.lock` (uv workspace of the Python sections), `.env.example`, `.dockerignore`, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`.

Where each section came from (the refactor of 2026-10-24 assembled the project from separate branches):

| Section | Assembled from |
|---|---|
| `collector/` | Go service of Alexandr (branch `tags`, in `main`): config, vocabulary of 525 tags, store, RSS collection of RBC/Kommersant/CBR, tagging worker, HTTP API, `llm/` client. Added: `sources.json` (merged `outlets50/outlets_new/outlets_regional.json`), generic RSS reader, Google News, resumable backfill, geotag; ported from Python `ingest.py`/`geotag.py` (branch `news_search/v1`) |
| `agents/` | LLM helpers scattered over `news_search/v1|v2` (`pipeline.py`, `analyze.py`), `ranking/reasoning-chain` (`reasoning/llm.py`, `alfa.py`); prompts from `prompt.md` and inline strings |
| `news_search/` | Branch `news_search/v2` (Goober-nation: bge-m3 over the corpus, xQuAD, pairs) as `dense_xquad`; branch `news_search/v1` as `dense_llm` and `lexical` (`lib.py`, `pipeline.py`); experiment findings in `news_search/benchmarks/` |
| `analytics/` | Branch `ranking/reasoning-chain` (Lev Vizan: `reasoning/chain.py`, `search.py`, `embed.py`, `alfa.py`, `roles.json`), switched from offline week cards to live search results |
| `backend/` | Mock server (`mock_server/`, UI contract) + `v1/v2` server and worker (profile queue, 24 h cache) + company card from bank CSVs (v2 `companies.py`, Lev's `company.py`) + role-line reading (`focus.py` of the reasoning branch) |
| `frontend/` | Former `ui/` (branch `ui/mockup-dashboard`), moved unchanged |
| `docker/` | Compose files of `v1/v2` and the Go service, rewritten as one stack |
| `docs/` | New per-section docs; Alexandr's `news-service.md` and `tag-vocabulary.md` kept as `collector-news-service.md`, `collector-tag-vocabulary.md` |

Architecture rules: every Python LLM call goes through `agents/` (the only exception is the Go tagging/geotag client in `collector/`); Postgres is shared (`collector` owns the corpus tables, `backend` owns `profiles`, the rest only read); sections talk HTTP/JSON and document their contract in their doc; the search method is picked by backend config, never hardcoded in a caller. Details: `docs/architecture.md`.

---

## 2. Working field

1. **At the start of every task, state which section it belongs to** (one section per task). If the section is not obvious, ask.
2. **New solutions are added modules, not rewrites.** A new search method is a new method of `NewsSearch`; a new LLM task is a new agent (prompt file + registry entry); a new endpoint is a new route. Existing code is changed only when the task is explicitly a fix or the user approves.
3. **If the task goes beyond the section's scope, say so plainly and ask the user to choose the concrete section** (or to split the task). Do not edit other sections' code on your own; propose the change.
4. Changing an algorithm needs a discussion with the user and an update of the section's doc in `docs/` with a simple, concise step-by-step walkthrough of how that part works.
5. A big change (new module, contract, dependency, multi-section change) needs an approved plan before any file is written. Plans are agreed in the dialogue and recorded in the GitHub issue of the task (https://github.com/one-zero-eight/hackathon-alfafuture/issues).

---

## 3. Branches, commits, the pre-commit check

- **Own branch for every substantial task, named `<section>/<feature>`**, section from the list above (`collector`, `agents`, `news_search`, `analytics`, `backend`, `frontend`, `docker`, `docs`), e.g. `news_search/hyde-cache`. Branch from `main`; no direct pushes to `main`; merge through a PR (a PR touching someone else's section needs their review).
- **A feature is not closed until its PR is closed (merged).** Do not mark the task done, close its GitHub issue, delete the branch or report the feature as finished while the PR is open; until then the status is "in review". Closing the issue is allowed only after the merge, or when the user says so.
- **Minor changes** (typos, small doc or config fixes, one-line fixes, no behavior or contract change) may be made without a separate branch, in the current working tree; the git-state rule below still applies (the user asks for commits). If the agent judges a change non-trivial, risky, or touching several files or sections, it proposes a separate branch and asks the user before creating it.
- **Commit format** (Russian): first line `<type>: <body>`, optional detail after a blank line. Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `build`, `bench`.
  ```
  feat: метод поиска по заголовкам без LLM

  Необязательное пояснение: зачем и что проверено.
  ```
- **No AI attribution** in commits or PRs (no `Co-Authored-By`, no "Generated with"), whatever a tool's default says.
- Git rules: read-only commands are free. Anything that changes repo state (`add`, `commit`, `push`, `rm`, `merge`, `rebase`, `reset`, discarding `checkout`/`restore`, branch creation/deletion) needs the user to ask for that specific action. Do not draft a commit message unprompted; drafting and approving are separate steps; a commit approval is not a push approval.
- **Before every commit, run `docker/check.sh` and fix what it reports.** It checks the compatibility of all sections for the final build: `uv.lock` is current; Python tests (with a throwaway Postgres); Go vet and tests; frontend tests and build; builds every image, starts the whole stack without host ports, and smoke-tests the links (frontend proxy -> backend, agents, news_search). If it cannot run, say so; do not claim a green check.
- Add one line to `CHANGELOG.md` for every real change of shared files: `- YYYY-MM-DD <section>: <what changed>.` (Russian, append-only at the bottom; never read the whole file, only `tail -n 10`; merge conflicts keep both sides, `.gitattributes` does it).
- **Docs stay in sync with the project.** After a change that touches files, endpoints, contracts, run commands, config or an algorithm of a section, check that its `README.md` and `docs/<section>.md` still match reality, and propose the doc update in the same task (Russian, per the language rule). **Before a commit** compare the staged changes with those two files; if they disagree (a file or route renamed or removed, a changed contract, a new env variable, a step of the walkthrough no longer true), do not commit: update the docs first and include them in the same commit, or tell the user which discrepancy blocks the commit. "Docs are fine" is stated only after the comparison was actually done.

### .gitignore check (also before every commit)

`.gitignore` is an allowlist: project source files and organizer materials are explicitly allowed; caches, environments, build output, secrets and run-time data are re-ignored for the whole repo, so no section needs its own. Before committing:
1. `git status --short --ignored` and look for stray caches or generated files inside every section (`__pycache__`, `.pytest_cache`, `node_modules`, `dist`, `.vite`, `*.npz`, `*.dump`, logs, local `.env`).
2. Anything generated that shows up as untracked: add a rule to the root `.gitignore`, do not commit it.
3. Nothing secret may be tracked: `.env` stays ignored, only `.env.example` is committed. Note that `external-docs/` is tracked and contains organizer data: check what you are adding.

---

## 4. Benchmarks

If a change affects quality, speed or cost (a new method, model, prompt or parameter), measure it:
- In the section folder create or open `benchmarks/` and add `<benchmark-name>.md` (lowercase, hyphens).
- Contents: what is measured and the hypothesis; the metric (units, formula, which direction is better); data and environment; the compared methods; a results table; a conclusion (what is chosen and why); limits; how to reproduce.
- Use the template `docs/benchmark-template.md`. Several runs of one benchmark go into the same file with dates.
- State what was not measured. Track LLM spend of anything that runs over many items.

---

## 5. Standing rules

- **Never guess or assume.** If a fact, requirement or decision is not in this file, `docs/`, the case brief or the user's words, ask. Do not invent endpoints, model names, data fields, tags or library behaviour: verify them.
- **No destructive action** (code, data, git) unless asked or approved. A teammate's work is changed only on the user's approval and if necessary.
- **Prove it works.** New non-trivial logic gets a small test. Every API/UI change is verified for real (endpoints with curl against the running stack; UI in a browser at desktop and mobile width, console errors). LLM integration is tested against the real approved API where feasible; otherwise say "unverified against real service". Do not imply coverage you do not have.
- **Lazy senior developer (Ponytail).** The best code is the code never written: reuse what exists, use the standard library or an installed dependency, no abstractions, options or config nobody asked for; never cut validation at trust boundaries, error handling that prevents data loss, security or accessibility. A shortcut with a known limit gets a comment `shortcut: <limit>, <when to upgrade>`. End a reply with one or two lines: what you skipped or did not check, and the risk.
- **LLM rules.** Only the approved models. The LLM never invents tags or industries outside the fixed vocabulary (extend it in `docs/` with team agreement). Never hardcode one-off processing of the Alfa PDFs: the pipeline accepts new PDFs.
- **Python tooling is uv**: `uv sync --all-packages`, `uv run pytest`, `uv lock` after changing dependencies (each section's `pyproject.toml`); no `pip` and no `requirements.txt`.
- **Escalation.** Tests fail 3 times: stop, document, revert, ask. Lint or build fails: one fix attempt, then ask. Never shotgun debug (hypothesis, test, verify). Stuck: describe the problem, propose 2-3 options, ask.
- **Docs.** `docs/` and section READMEs must not point into ignored scratch paths; inline the needed fact.
- **Tasks** live as GitHub issues in `one-zero-eight/hackathon-alfafuture` (use `gh issue`). Before starting, read the issue; when finishing, add a comment with what was verified. If a free-form idea arrives, propose creating an issue before acting.
- **Communication**: concise, no flattery; ask when scope is ambiguous, propose solutions rather than only problems; during planning ask with `AskUserQuestion` instead of assuming. After implementation give the exact commands to run, test and exercise it (curl examples, prerequisites).

**Computational resources**: team server with Tesla V100 32 GB, 60 CPU cores, 190 GB RAM, 3 TB disk. Ask the user about local hardware, it differs per person.

**Open questions (do not assume answers)**: format of the risk assessment in the output; event cards (cause -> effect) for live news are not built, so analytics works without them; owners of the new sections; whether the tag graph is revived (it lost to embeddings in the experiments).
