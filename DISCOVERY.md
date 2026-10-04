# Phase 0 discovery

Date: 2026-10-04 (Asia/Calcutta)

## Source and license

- Upstream: https://github.com/HKUDS/nanobot (HKUDS/nanobot), cloned from `main`.
- Checkout commit: `fb059d555c7683c7fff184a0a1224d847ee652c2`.
- License: MIT (`LICENSE`, copyright 2025-present Xubin Ren and nanobot contributors). Preserve `LICENSE` and `THIRD_PARTY_NOTICES.md` in redistributed builds; inspect dependency and bundled UI/TUI notices before packaging.
- This is nanobot v0.3.5 (`pyproject.toml`), Python >=3.11. It is substantially larger and more feature-rich than the “small harness” assumed by the TRD. Do not claim measured upstream diff sizes until implementation exists.

## Baseline run

The live OpenAI/Telegram baseline is deferred per the user's instruction to leave the OpenAI key for later. No `OPENAI_API_KEY` environment variable or `~/.nanobot/config.json` is present. Telegram token/config availability was not established.

- Python 3.13.2 is available by invoking its full executable path. A project-local `.venv` was created with `uv`; it contains no nanobot dependencies yet.
- `python -m nanobot --version` could not start because nanobot was not installed. A source import attempt then stopped at missing `loguru`.
- Installing the upstream dependency set with `uv pip install -e .` failed in the sandbox because the package index hostname could not be resolved. Do not treat the upstream runtime as installed.
- The new Simo Phase M1 boundary code uses the standard library; focused unit tests run using the host Python's existing pytest. They do not exercise a live provider.

The request explicitly authorizes proceeding with offline development while deferring the live-provider check. No credential or real student data is stored in this repository.

### M1 offline implementation status

- `simo/config.py`, `identity.py`, `egress.py`, and `llm.py` implement local settings, the teacher-side name vault, a fail-closed roster scan, and the OpenAI-compatible live/record/replay client.
- `nanobot/providers/base.py` now has a separate fail-closed guard on retry-managed privileged-agent calls. `simo/provider_guard.py` attaches the guard; Simo builds must call it when constructing their provider.
- Nine focused standard-library Simo tests pass using host pytest, covering pseudonymization, roster egress blocks, pre-transport checks, bounded retries/tokens, JSON repair, and synthetic record/replay. The upstream provider-path regression test is written but could not run because the upstream dependency set is not installed.
- Live OpenAI and Telegram smoke checks remain pending by user choice.

### M2 offline implementation status

- `simo/schemas.py` and `rubric.py` enforce strict rubric and reader-output contracts, an acyclic concept graph, unique IDs, increasing finite non-negative marks, level-only model scoring, and teacher override recomputation.
- `simo/db.py` creates a versioned SQLite schema with foreign keys and teacher/class scoping. Roster identity reads and submission/rubric queries require both tenant keys; stored submissions contain only scrubbed text.
- Sixteen focused Simo tests pass, including rubric validation/scoring and database persistence/scope checks. No real learner data is present.

### M3 offline implementation status

- `simo/reader.py` sends one scrubbed submission plus rubric in a two-message, tool-less request; typed validation allows one schema repair without echoing invalid model output.
- `simo/verify.py` recomputes points from rubric levels, matches evidence against normalized scrubbed text, checks injection and confidence signals, routes short top-level answers and sample disagreement to review, and persists proposals without replacing teacher overrides.
- `simo/workflow.py` adds tenant-scoped run checks, persisted read/verify steps, sample grading, token restoration, and partial-run resume. Run summaries contain IDs, rubric results, and flags rather than submission text or quotes.
- SQLite schema v2 adds persisted step results with a v1 migration. The 23 focused offline Simo tests pass, including reader isolation, bad-output repair, evidence/injection checks, cached steps, and partial resume.
- Live provider checks and the upstream provider regression test remain unverified: the key is deferred and upstream runtime dependencies could not be installed in the sandbox. This host's Python 3.13 asyncio event-loop socketpair startup also hangs, so offline tests use synchronous fake readers and a small coroutine runner; live async transport has not been exercised here.

### M4 offline policy and approval core

- `simo/policy.py` adds an explicit READ/WRITE_LOCAL/RELEASE tool registry, fail-closed allowlist, and teacher-authenticated write checks. Denials and decisions are persisted as scoped policy events without tool arguments.
- `simo/approvals.py` issues out-of-band, one-use HMAC capabilities. Resolution checks teacher/class scope, expiry, pending state, and HMAC; release checks the current artifact hash and expiration, so editing a draft invalidates prior approval.
- Offline tests cover unregistered shell denial, authenticated writes, missing approval, bad/reused/expired approval, cross-tenant scope, artifact edits, and persisted decision events. All 26 focused tests pass.
- `simo/nanobot_adapter.py` now builds nanobot's actual `ToolRegistry` with only explicitly supplied Simo tool definitions. Each adapter tool enforces policy inside its `execute` method (the upstream dispatcher directly invokes that method after preparation); unknown tool calls are denied and audited. The runtime adapter could only be byte-compiled here because nanobot's installed dependency set is unavailable, and no concrete workflow/release tools are registered yet. Keep general tools out of the injected registry. Approval secret provisioning remains a deployment setup item independent of the deferred OpenAI key.

### M5 offline diagnosis and reporting core

- `simo/diagnose.py` adds authenticated accept/override operations, rubric-recomputed override points, and idempotently rebuilt mistake events sourced only from accepted or overridden judgments.
- Gap claims require the configured minimum event and distinct-question counts (defaults: 2 and 2); weaker evidence is labeled possible and requires a diagnostic probe. Recommendations weight gaps by rubric points and probe a prerequisite when its verified evidence is weaker.
- `class_report` returns review counts, scoped error-tag counts, only threshold-verified shared gaps, and students without a verified gap. Reports and recommendations are produced from persisted data and contain no submission text or learner names.
- Offline tests verify one-event possible gaps, two-question verified gaps, prerequisite probes, shared-gap reporting, teacher-only overrides, recomputed points, and event removal after a top-level override. The focused suite now has 28 passing tests. The same pass exposed and fixed strict JSON enum decoding for model outputs and cached workflow steps.
- The scoped nanobot registry adapter is available, but concrete teacher-facing tool registration remains integration work; do not route diagnosis data through a general-purpose agent registry.

### M6 offline evaluation harness status

- `eval/gold.json` and `eval/rubric.json` add 18 synthetic cases, including six planted injection attempts. Labels are explicitly marked as builder-assigned and are not a teacher-panel validation set.
- `eval/run_baseline.py` and `eval/run_simo.py` create comparable prediction files without storing answer text in those outputs. `eval/report.py` computes agreement, weighted kappa, error-tag accuracy, evidence verification, review precision/recall, injection outcomes, out-of-range score rate, tokens, and latency.
- Report generation requires complete prediction IDs; no predictions or model scores are fabricated or committed. API and local-model matrix runs remain pending until credentials and a local model endpoint are configured. Thirty focused offline tests pass; the report CLI help and Python compilation were checked.

### M7 documentation and advisory skill status

- The root README states the current capabilities and deployment gaps, gives offline test and rubric-validation commands, and keeps the live demo explicitly pending.
- `skills/rubric-grading/SKILL.md` covers observable rubric levels, evidence/flag interpretation, teacher approval boundaries, and privacy. Its name, directory match, required front matter, field limits, and body layout were checked against the [Agent Skills specification](https://openagentskills.dev/docs/specification); the bundled `quick_validate.py` also reports “Skill is valid.” The official `skills-ref` CLI is not installed in this offline checkout.
- `scripts/validate_rubric.py` uses the same `Rubric` schema as grading and successfully validates `eval/rubric.json`. M7's live demo items remain pending: the OpenAI key is deferred, no local model endpoint is configured, and upstream dependencies could not be installed.

## Internals observed

- **Agent loop / tool dispatch:** `nanobot/agent/runner.py:490-520` handles a model response and calls `execute_tool_calls`. The central per-call dispatch is `nanobot/agent/tools/execution.py:115-216`; after `prepare_call`, it runs `hook.before_execute_tool(...)` then invokes `tool.execute(...)` or `ToolRegistry.execute(...)` (`registry.py:187`). `ToolRegistry.register` and tool lookup live in `nanobot/agent/tools/registry.py:19-36`.
- **Policy hook:** `AgentHook.before_execute_tool` exists (`agent/hook.py:108`), but `AgentHookChain._for_each_hook_safe` catches/logs exceptions by default (`hook.py:175-188`). It cannot enforce deny/needs-approval as written. Smallest robust approach: put Simo's allow/deny/approval decision in a Simo-owned tool wrapper/registry dispatch path that returns a typed denial before underlying execution; if adding an upstream hook, give policy rejection a dedicated explicit result/exception path that cannot be swallowed by error-isolating observer hooks. Expected upstream diff: isolated change around `agent/tools/execution.py` plus focused tests; exact size TBD.
- **Tool allowlist:** `AgentLoop` accepts a `ToolRegistry` (`agent/loop.py:274,379`); session policy can filter disabled tools (`agent/loop.py:1948+`). Register only Simo tools in a dedicated registry, and do not expose general shell/file/web tools. The session disabled list is a denylist, not a sufficient Simo allowlist by itself.
- **Provider / model calls:** `LLMProvider` owns retry-managed model calls (`providers/base.py:636+`), and OpenAI-compatible provider config passes `api_base` to `AsyncOpenAI(base_url=...)` (`providers/openai_compat_provider.py:605-607`). `LLMProvider.set_llm_call_observer` exists, but `_observe_llm_call` catches observer exceptions (`providers/base.py:780-814`) and the observer sees response/usage records after calls; it is not a blocking egress boundary. M1 adds a separate fail-closed request guard to the retry-managed chat and stream paths (`providers/base.py`), and `simo/provider_guard.py` installs Simo's roster check there. The Simo-owned reader client checks its request immediately before send. Direct calls that bypass these paths must remain disabled or be separately guarded; verify every enabled provider path before claiming full coverage.
- **Channel boundary:** Telegram converts an authorized update into text/media and forwards it from `nanobot/channels/telegram/runtime.py:1960+` via `_process_message_update` and `_handle_message`. There is no identified generic identity-transform hook from this inspection. A Simo-only channel ingress/egress wrapper can pseudonymize after teacher authentication and re-identify only teacher-facing replies. Keep real roster data out of nanobot prompt/session state. Confirm exact gateway integration before implementation.
- **Callbacks:** Telegram registers `CallbackQueryHandler` (`channels/telegram/runtime.py:730`) and implements `_on_callback_query` (`:2211+`). Callback-based approval is feasible on Telegram. It must be authenticated and routed directly to Simo's approval resolver, never converted into an agent instruction/tool call. The CLI fallback remains available for non-Telegram use.
- **Memory / skills:** nanobot has persistent sessions and workspace skills. `AgentLoop`/`ContextBuilder` load enabled skills; `AgentDefaults.disabled_skills` exists in `config/schema.py:147`. Simo should disable unneeded skills and use its own constrained rubric-grading skill. Existing memory/session persistence must not receive real student submissions or names.

## Phase 0 decisions and deviations

1. Base: use the pinned checkout above; preserve its license and notices. The current source is not the lightweight assumed base, so keep Simo code isolated and avoid broad renaming/rework.
2. Policy: use a Simo-owned enforcement boundary with explicit deny semantics; the observer hook is not a policy mechanism.
3. Egress: the upstream usage observer is post-call/fail-open. M1 adds pre-send request validation for Simo's reader and a fail-closed check at nanobot's retry-managed provider boundary. Simo runtime construction must install the guard and avoid direct unguarded provider calls.
4. Identity: no reusable general channel transform was confirmed. Start with a Simo-specific authenticated channel ingress/egress adapter; do not keep a roster mapping in agent/session context.
5. Approval: use Telegram callback queries if Telegram is selected, resolving an opaque, one-time Simo capability out of band. Retain local CLI approval as fallback. Callback behavior/authentication still needs focused confirmation.
6. **Live baseline deferred.** The mandatory unmodified OpenAI/Telegram baseline has not run: the OpenAI key is intentionally deferred, Telegram config is unconfirmed, and upstream dependencies are not installed. The user authorized moving ahead with offline M1 work; run and record the live baseline when credentials are configured. Keep this limitation visible in the README until then.

## Commands and references

- Clone: `git clone --depth 1 https://github.com/HKUDS/nanobot.git nanobot-base`
- Source status: `git -C nanobot-base status --short --branch`
- Commit: `git -C nanobot-base rev-parse HEAD`
- Relevant files: `nanobot/agent/runner.py`, `nanobot/agent/tools/execution.py`, `nanobot/agent/tools/registry.py`, `nanobot/agent/hook.py`, `nanobot/providers/base.py`, `nanobot/providers/openai_compat_provider.py`, `nanobot/channels/telegram/runtime.py`, `nanobot/config/schema.py`.
