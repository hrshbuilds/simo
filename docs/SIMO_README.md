# Simo

Simo is an open-source, privacy-first harness for teachers' daily workflow. This repository builds on the MIT-licensed [nanobot](https://github.com/HKUDS/nanobot) project. See [DISCOVERY.md](../DISCOVERY.md) for the upstream revision, source findings, phase status, and known limits; the original request is preserved in [TRD.md](TRD.md).

## Current state

Offline milestones M1–M7 have core implementations: guarded model access, identity and egress helpers, rubric schemas and scoring, SQLite storage, an isolated reader and verifier, resumable grading, policy and approval primitives, teacher review and diagnosis logic, an evaluation harness, project docs, and an advisory skill. The detailed status is in `DISCOVERY.md`.

The project is not yet a ready-to-use teacher application. Nanobot runtime dependencies are not installed in the current checkout, the channel identity boundary and concrete teacher tools are not wired, the upstream AgentLoop adapter has only been compiled (not run), and no model evaluation has been measured. The OpenAI API key is intentionally deferred. Do not use real student data until the channel boundary, tool registration, review rendering, and deployment storage have been implemented and reviewed.

## Development

Use Python 3.11 or newer. Install the project and test dependencies when package-index access is available:

```powershell
uv sync --extra dev
```

Run the focused offline Simo suite:

```powershell
python -m pytest --confcutdir=tests\simo tests\simo -q
```

Validate a rubric with the same Pydantic schema used by the workflow:

```powershell
python scripts\validate_rubric.py eval\rubric.json
```

For endpoint checks, set `LLM_API_KEY`, `LLM_MODEL`, and optionally `LLM_BASE_URL` in the process environment. Do not commit secrets. Do not record real answers: record mode requires explicit `CASSETTE_ALLOW_TEXT=true` because requests and responses may contain verbatim student text.

## Evaluation

The synthetic evaluation set and commands are documented in [eval/README.md](../eval/README.md). It contains builder-assigned labels and is not a validated educational assessment. Reports are produced only from actual prediction files; the model runs have not been performed yet.

## Skill

The advisory [`rubric-grading` skill](../skills/rubric-grading/SKILL.md) describes rubric authoring and interpretation. The harness, not the skill, enforces scoring and review rules.
