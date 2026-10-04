# TRD: Simo — an open-source, privacy-first harness for teachers' daily workflow

Audience: Codex (builder) and the human reviewing it. Fork base: **nanobot** (open-source agent harness). Demo model API: **OpenAI API**, behind an OpenAI-compatible client so a local **open-weight** model works by config only.

> **Read this first.** This document was written without reading the nanobot source. Everything about nanobot internals (file names, hooks, config keys, channel callbacks) is an **assumption until Phase 0 confirms it**. If Phase 0 contradicts this TRD, stop, record the finding in `DISCOVERY.md`, and propose the smallest change. Never invent APIs. Every guarantee in this document must end up backed by a test or a measured result (section 14). Do not claim anything the evidence does not support.

---

## 1. Product scope (replaces the old PRD for this build)

**Users:** school or college teachers and tutors.

**The loop we build:** *check student work → explain why it went wrong → decide what each student should learn next → draft the fix.* This one loop covers the teacher's most painful tasks: checking and evaluating work, analyzing mistakes, tracking progress, deciding what to teach next, and remedial teaching.

**Scope (priority):**

| Pri | Capability |
|---|---|
| P0 | Rubric-bound grading of **typed/pasted text** answers, with evidence, review queue, teacher override |
| P0 | Mistake diagnosis per criterion; per-student and per-class gap profile; next-step recommendation |
| P0 | Pseudonymization boundary and egress guard (no real names reach any model) |
| P0 | Teacher-approval capabilities for anything that leaves the teacher's machine |
| P0 | Evaluation harness with synthetic gold data and a baseline-vs-harness ablation |
| P1 | Consistency checks (similar answers, similar marks) and double-grading |
| P1 | Remedial worksheet draft for a student or a group sharing a gap |
| P2 | Resumable runs, teacher style memory, model comparison matrix, follow-up and parent-message drafts |

**Out of scope:** handwriting/OCR, attendance, fees, scheduling, real student data in the repo, any automatic sending without approval.

**Pitch line:** *An open-source, privacy-first teacher co-pilot that checks student work, explains why students went wrong, and drafts the next step, with every mark and message approved by the teacher.*

---

## 2. Why this is a harness and not an LLM wrapper (the defense)

A wrapper sends text to a model and shows what comes back. In Simo the **model's output is an untrusted proposal**, and the surrounding system, not the model, owns correctness, safety, and state.

| Concern | A wrapper | Simo (harness-owned, in code) |
|---|---|---|
| Marks and totals | Model writes a number | Model picks a **discrete rubric level**; points, totals, and bounds are computed by code |
| Evidence | Model says why | Every judgment must cite **verbatim quotes** from the submission; code string-matches them; unverified judgments are downgraded to review |
| Prompt injection from student answers | Hope the prompt resists | **Quarantined reader** with no tools and schema-only output; privileged agent never sees raw student text; bounded blast radius; tested with an attack suite |
| Student privacy | A line in the prompt | **Identity boundary** at the channel edge plus an **egress guard** that scans every outbound model request for roster names and blocks it |
| Release to students/parents | Model decides to send | **Hash-bound approval capabilities** resolved only by a path the agent has no tool for |
| "This student has gap X" | Model's impression | **Verified-claim gate**: a gap is asserted only when aggregated evidence meets a threshold; otherwise the system proposes a probe question |
| Reliability | One call, no recovery | Retries, JSON repair, double-grading with disagreement routing, budgets, resumable runs |
| Reproducibility | None | **Record/replay** of every model call; tests and evals run offline and deterministically |
| Trust claims | Marketing | **Eval harness** with a baseline-wrapper ablation on the same data |
| Portability | One provider | One client, per-model capability adapters, tested on OpenAI API and a local open-weight model |

**Upstream changes to nanobot (the "meaningful changes" claim)** are listed in section 15 and must appear in the README as a table with file paths and diff sizes.

---

## 3. Design principles

1. **Propose / decide split.** Models propose; deterministic code decides. Anything a guarantee depends on is enforced in code.
2. **Quarantine untrusted content.** Student submissions are adversarial input. Only a tool-less, schema-constrained reader touches them. The privileged agent sees typed fields and IDs, not raw text.
3. **Least information.** Models get pseudonyms, not names; the agent gets summaries, not submissions; no model ever gets secrets.
4. **Capabilities, not conversation.** Approvals are records bound to a specific artifact hash, resolved out-of-band. Chat text cannot grant them.
5. **Deterministic where possible.** Scoring, aggregation, consistency checks, ranking, and gap claims are plain Python.
6. **Everything is evidenced and replayable.** Every model call, policy decision, and state change is traced; every claim ties to a test or a measurement.
7. **Smallest possible upstream diff.** New logic in `simo/`; minimal, isolated edits in nanobot.

---

## 4. Architecture

```
Teacher (Telegram / CLI)                      Teacher-side only: real names, roster
        |                                      ────────────────────────────────
   [ IDENTITY BOUNDARY ]  inbound: names -> pseudonyms | outbound: pseudonyms -> names
        |
   nanobot channel adapter ──> nanobot agent loop (privileged agent; restricted profile)
                                   |  tool call
                            [ POLICY HOOK ]  (single dispatch point; allow / deny / needs-approval)
                                   |
                           simo tools ──> Workflow engine (persisted runs)
                                   |                 |
                                   |        step: QUARANTINED READER (no tools, schema-only)
                                   |                 |
                                   |        step: DETERMINISTIC VERIFIERS (bounds, evidence match,
                                   |              consistency, aggregation, gap-claim gate)
                                   |
                          SQLite (rubrics, submissions, marks, events, approvals, profiles)
                                   |
        LLM client (OpenAI-compatible) ── [ EGRESS GUARD ] ── record / replay / live ── trace.jsonl
                                   |
   Approval resolver (button callback / local CLI)  <── out-of-band, no agent tool reaches it
```

Two model roles:
- **Privileged agent** (nanobot loop): converses with the teacher, chooses tools, relays results. Sees pseudonyms, IDs, counts, typed flags. **Never sees raw student text or answer keys.**
- **Quarantined reader**: called from inside workflow steps. No tools, no memory, no access to anything but one delimited submission plus the rubric. Output must validate against a JSON schema; otherwise it is retried or flagged. Its output is **data, never instructions**.

---

## 5. Phase 0 — discovery (do first, about 45 min)

Write findings to `DISCOVERY.md` with file paths and line references.

1. Fork and clone nanobot; record license, notice requirements, and commit hash.
2. Run the unmodified project on the OpenAI API on one channel (Telegram preferred; CLI fallback). Record working commands.
3. Document: the agent loop; the tool registry and **the single tool-dispatch point**; how tools are defined; the provider/LLM layer and whether a base URL can be set; where **all** model calls pass (agent's own calls and tool-internal calls); the channel adapter's inbound/outbound message path (can a transform be inserted?); whether channels support **button callbacks**; the built-in memory; how to disable or allowlist tools; where skills load from.
4. Decide, and record with intended diff size: (a) policy hook strategy, (b) where the egress guard attaches (provider layer preferred, so it covers every call), (c) where the identity boundary attaches (channel adapter preferred), (d) how approvals are resolved if buttons are unavailable (fallback: a local CLI `simo approve <id>` or a small localhost page, outside the agent's tool surface).
5. List any guarantee in this TRD that cannot be met as written, with the smallest alternative.

**Exit criteria:** baseline runs; `DISCOVERY.md` committed; hook points identified; license recorded. Do not start M1 without these.

---

## 6. Repository layout (adapt after Phase 0)

```
<forked-repo>/
  LICENSE  README.md  DISCOVERY.md  docs/TRD.md
  simo/
    config.py            # env, constants, thresholds
    db.py                # SQLite + migrations
    llm.py               # OpenAI-compatible client; modes: live | record | replay; retries; JSON repair; budgets
    egress.py            # EgressGuard: scans outbound payloads for roster names/IDs; blocks on hit
    identity.py          # roster vault, pseudonymize()/reidentify(), name-variant matching
    rubric.py            # rubric schema, validation, level->points mapping, scoring (pure)
    schemas.py           # pydantic: rubric, reader output, tool I/O
    reader.py            # QuarantinedReader: prompt, call, validate, repair
    verify.py            # evidence verification, injection heuristics, bounds, anomaly flags
    workflow.py          # persisted runs/steps, idempotency, budgets, resume
    consistency.py       # similarity + mark-divergence flags (P1)
    diagnose.py          # mistake events, aggregation, gap-claim gate, probes, recommend_next
    remedial.py          # worksheet draft + verification (P1)
    approvals.py         # approval records, hash binding, HMAC callbacks, expiry
    policy.py            # PolicyEngine and rules
    render.py            # template-based rendering of teacher-facing views (no LLM)
    tools.py             # tools registered for the simo profile
    prompts.py           # agent system prompt + reader prompts
    trace.py             # JSONL tracing, redaction
  skills/rubric-grading/
    SKILL.md  references/rubric-format.md  scripts/validate_rubric.py
  eval/
    data/                # synthetic gold set (see section 14) — NO real student data
    run_eval.py  baseline_wrapper.py  report.py
    cassettes/           # recorded model calls for offline replay
  tests/
  scripts/  show_trace.py  smoke_llm.py  approve.py
  .env.example
```

---

## 7. Configuration

```
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=changeme
LLM_MODEL=<set a current, inexpensive model>
LLM_MODE=live                 # live | record | replay
CASSETTE_DIR=./eval/cassettes
GRADE_SAMPLES=2               # double-grading; 1 disables
MAX_RUN_TOKENS=<set a budget>
MAX_RETRIES=2
APPROVAL_SECRET=<random>      # HMAC for approval callbacks; never shown to any model
SIMO_DB=./data/simo.db
TRACE_PATH=./data/trace.jsonl
TRACE_INCLUDE_TEXT=false      # redact student text and quotes by default
TOOL_PROFILE=simo
```

Local open-weight run: `LLM_BASE_URL=http://localhost:11434/v1` (Ollama or any OpenAI-compatible server), `LLM_API_KEY=ollama`, `LLM_MODEL=<local model>`. Document verified working values in the README. Never hard-code keys or model names. Never commit `.env`, `data/`, or any real student information.

---

## 8. Data model (SQLite; every query scoped by teacher/class)

```sql
CREATE TABLE roster (            -- identity vault; NEVER readable by model-facing code paths
  student_id TEXT PRIMARY KEY,   -- internal id
  pseudonym  TEXT UNIQUE NOT NULL,   -- e.g. S-7F3A
  real_name  TEXT NOT NULL,
  name_variants TEXT NOT NULL DEFAULT '[]'  -- JSON: nicknames, initials, spellings
);

CREATE TABLE rubrics (
  id TEXT PRIMARY KEY, title TEXT, json TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT
);

CREATE TABLE concepts (
  id TEXT PRIMARY KEY, rubric_id TEXT, title TEXT,
  prerequisites TEXT NOT NULL DEFAULT '[]'      -- JSON array of concept ids (teacher-approved graph)
);

CREATE TABLE assessments (id TEXT PRIMARY KEY, rubric_id TEXT, title TEXT, created_at TEXT);

CREATE TABLE submissions (
  id TEXT PRIMARY KEY, assessment_id TEXT, student_id TEXT,
  question_id TEXT, text_scrubbed TEXT NOT NULL,   -- scrubbed copy used by models
  text_sha256 TEXT NOT NULL, created_at TEXT
);

CREATE TABLE judgments (          -- per submission per criterion; reader proposals after verification
  id INTEGER PRIMARY KEY, submission_id TEXT, criterion_id TEXT,
  level_id TEXT NOT NULL, points REAL NOT NULL,     -- points computed by code from level_id
  evidence TEXT NOT NULL,                           -- JSON: verified quotes only
  evidence_verified INTEGER NOT NULL,
  error_tag TEXT, confidence REAL, samples_agree INTEGER,
  flags TEXT NOT NULL DEFAULT '[]',                 -- e.g. ["low_confidence","disagreement","injection_suspected"]
  status TEXT NOT NULL DEFAULT 'proposed',          -- proposed | needs_review | accepted | overridden
  teacher_level_id TEXT, teacher_reason TEXT, updated_at TEXT
);

CREATE TABLE mistake_events (     -- feeds diagnosis; only from accepted/overridden judgments
  id INTEGER PRIMARY KEY, student_id TEXT, concept_id TEXT, assessment_id TEXT,
  criterion_id TEXT, error_tag TEXT, evidence_ref INTEGER REFERENCES judgments(id), created_at TEXT
);

CREATE TABLE artifacts (          -- anything that may leave the teacher's machine
  id TEXT PRIMARY KEY, kind TEXT,                   -- feedback | worksheet | marks_export | parent_message
  body TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT
);

CREATE TABLE approvals (
  id TEXT PRIMARY KEY, artifact_id TEXT, artifact_sha256 TEXT NOT NULL,
  action TEXT NOT NULL,                             -- release | export
  status TEXT NOT NULL DEFAULT 'pending',           -- pending | approved | rejected | expired | revoked
  nonce TEXT NOT NULL, created_at TEXT, resolved_at TEXT, expires_at TEXT
);

CREATE TABLE runs      (id TEXT PRIMARY KEY, assessment_id TEXT, status TEXT, tokens_used INTEGER, started_at TEXT, finished_at TEXT);
CREATE TABLE run_steps (run_id TEXT, item_id TEXT, step TEXT, attempt INTEGER, status TEXT, output_sha256 TEXT, error TEXT, PRIMARY KEY (run_id, item_id, step));
CREATE TABLE events    (id INTEGER PRIMARY KEY, kind TEXT, payload TEXT, created_at TEXT);
```

Writes to `judgments.points`, `status`, and `mistake_events` happen only through `rubric.py`, `verify.py`, and `diagnose.py` (checked by test T14).

---

## 9. Rubric engine (pure code)

Rubric JSON (teacher-authored or teacher-approved; validated on load):

```json
{
  "rubric_id": "sci-forces-01",
  "title": "Forces: short answers",
  "concepts": [
    {"id": "forces_basic", "title": "Types of forces", "prerequisites": []},
    {"id": "newton2", "title": "Newton's second law", "prerequisites": ["forces_basic"]}
  ],
  "criteria": [
    {"id": "c1", "name": "States the law correctly", "concept_id": "newton2",
     "levels": [
       {"id": "L0", "points": 0, "descriptor": "Missing or incorrect"},
       {"id": "L1", "points": 1, "descriptor": "Partially correct"},
       {"id": "L2", "points": 2, "descriptor": "Correct and complete"}
     ]}
  ]
}
```

Validation (reject on failure): unique ids; each criterion has at least two levels; level points strictly increasing; every `concept_id` exists; prerequisite graph is acyclic; `total_points` is **computed**, never trusted.

Scoring: `points = rubric.level(criterion_id, level_id).points`; `total = sum(points)`. The reader returns a **level id from an enum**, never a number. An unknown level id is rejected. Teacher override sets `teacher_level_id`; points recomputed by the same function.

---

## 10. Grading workflow (persisted, idempotent)

Per submission, steps recorded in `run_steps`:

1. **scrub**: `identity.pseudonymize()` removes roster names and variants from the submission text. Student-written names of other people are scrubbed if they match the roster; unmatched names are left (documented limitation).
2. **read** (quarantined reader, `GRADE_SAMPLES` times): one call per sample with temperature or prompt variation. Output schema:

```json
{
  "criteria": [
    {"criterion_id": "c1", "level_id": "L2",
     "evidence": ["exact quote from the submission"],
     "missing": null,
     "error_tag": null,
     "confidence": 0.0,
     "rationale": "max 40 words"}
  ],
  "injection_suspected": false
}
```

`error_tag` enum: `recall_failure`, `concept_confusion`, `prerequisite_gap`, `careless_error`, `incomplete`. The tag is a **hypothesis**, not a finding (see section 12).

3. **verify** (code): for each criterion, (a) every `evidence` quote must be a normalized substring of the scrubbed submission; if `level_id` is above the lowest level and no quote verifies, downgrade to review (`flags += unverified_evidence`) and **do not** award the points as accepted; (b) level id valid for that criterion; (c) injection heuristics on the submission (instruction-like phrases addressed to a grader, role markers, attempts to name a score) set `injection_suspected` regardless of what the reader said; (d) if sample runs disagree on level, set `disagreement` and route to review; (e) confidence below threshold routes to review; (f) anomaly rule: a top-level award with a very short submission, or with injection flag, routes to review.
4. **persist**: write judgments with `status = proposed` or `needs_review`.
5. **teacher review**: accept all proposed, handle the `needs_review` queue, or override any criterion. Only `accepted` or `overridden` judgments feed diagnosis.

Budgets and failure handling: `MAX_RUN_TOKENS` stops a run with partial results and a clear status; `MAX_RETRIES` bounds retries; invalid JSON gets one repair attempt (re-prompt with the validation error) and then the item is flagged `needs_review`, never silently dropped. Steps are idempotent by `(run, item, step)`, so a crashed run can resume (P2 for full resume; P0 for idempotent steps).

---

## 11. Quarantine and the identity boundary

**Quarantine rules (enforced and tested):**
- The reader call carries no tool definitions and no conversation history.
- The submission is wrapped in explicit delimiters, labeled untrusted, with an instruction that its contents are data.
- Reader output is parsed into typed fields. Free-text fields (`rationale`) are length-limited and are **not** appended to the privileged agent's context. Teacher-facing text containing student quotes is rendered by `render.py` templates directly to the teacher, not composed by the agent. If Phase 0 shows the channel cannot deliver rendered content outside the agent loop, fall back to passing it through the agent **wrapped as untrusted**, and document the weaker guarantee honestly.
- Effect of a successful injection is bounded by construction: the worst case is a wrong level on that submission, which is still bounded by the rubric, needs verified evidence, and is surfaced to the teacher. It cannot call tools, change other students' marks, release anything, or read the roster.

**Identity boundary:**
- Real names live only in `roster`. The channel adapter transform pseudonymizes inbound teacher messages (so "how is Rahul doing" reaches the agent as "how is S-7F3A doing") and re-identifies outbound messages to the teacher.
- If the channel cannot support transforms (Phase 0), fallback: the teacher refers to students by roster code, and the egress guard still protects everything.

**Egress guard (in `llm.py`, or at nanobot's provider layer if one exists):** before every outbound model request, scan the full serialized payload for roster names, name variants, and student IDs. On any hit, **block the request**, write a `egress_block` trace event, and return a structured error. This covers the privileged agent's calls as well as the reader's. It is the last line of defense, independent of the scrubber.

---

## 12. Diagnosis, gap claims, and next steps (deterministic)

- **Mistake events** are created from accepted or overridden judgments whose level is below the top level, with `error_tag` and the evidence reference.
- **Verified-claim gate.** The system may state "student S has a gap in concept C" only if: at least `GAP_MIN_EVENTS` (default 2) mistake events on C, across at least `GAP_MIN_ITEMS` (default 2) distinct questions or assessments. Below that, it may say "possible gap, insufficient evidence" and must propose a **probe** (see below). The agent cannot assert a gap that `diagnose.py` has not returned.
- **Prerequisite hypothesis.** A `prerequisite_gap` tag proposes that the real problem is upstream. The system tests it by checking the student's evidence on prerequisite concepts; if there is none, `recommend_next` returns a **diagnostic probe** (a short targeted item on the prerequisite) instead of asserting.
- **`recommend_next` (pure code):** for a student, rank concepts by `(gap_strength) × (rubric weight)`; if the top concept has a prerequisite with weaker evidence, recommend the prerequisite first. For a class, group students by shared verified gaps and return group sizes.
- **Class report:** counts per concept and error tag, top shared gaps, review queue size, students with insufficient evidence. All numbers come from SQL, rendered by templates.

---

## 13. Policy engine, approvals, and the restricted profile

**Hook** at the single dispatch point found in Phase 0:

```python
decision = policy.check(tool_name, args, ctx)
trace.log("policy_decision", tool=tool_name, decision=asdict(decision))
if decision.kind == "deny":            return structured_denial(decision)
if decision.kind == "needs_approval":  return create_pending_approval(tool_name, args, ctx)
result = tool.run(args, ctx)
```

**Tool classes:** `READ`, `WRITE_LOCAL`, `RELEASE`. Every tool declares its class in registration.

**Rules:**

| ID | Rule |
|---|---|
| P1 | **Allowlist.** Only the `simo` tool set is callable; shell, file, and web tools are denied (profile). |
| P2 | **Release requires an approved capability.** `RELEASE` tools (`release_artifact`) run only if an `approvals` row exists with `status=approved`, matching `artifact_id`, **`artifact_sha256` equal to the current artifact hash**, and not expired. Editing an artifact changes its hash and voids the approval. |
| P3 | **Agents cannot resolve approvals.** No tool exists that sets `approvals.status`. Resolution happens only in `approvals.resolve()`, invoked by the button-callback handler or the local CLI, verifying an HMAC over `(approval_id, nonce)` with `APPROVAL_SECRET`, one-time use. |
| P4 | **Teacher-only mutations.** `override_mark` is accepted only from a teacher-authenticated channel context, never from reader output. |
| P5 | **No mark or diagnosis writes from tools directly.** Marks and mistake events are written only by pipeline code (`verify.py`, `diagnose.py`). Static test enforces this. |
| P6 | **Scope.** All object ids must belong to the current teacher/class; otherwise deny. |
| P7 | **Reader isolation.** The reader call path must not receive tool definitions or history (asserted at the `reader.py` call site and tested). |
| P8 | **Gap claims.** Tools returning "gap" language must include only claims produced by `diagnose.py` (typed `Claim` objects with evidence counts). |

**Tools (all take teacher/class context from the harness, not from model arguments):**

| Tool | Class | Notes |
|---|---|---|
| `load_rubric` | WRITE_LOCAL | Validates; returns concept and criterion summary |
| `import_roster` | WRITE_LOCAL | CSV into the vault; returns counts only |
| `import_submissions` | WRITE_LOCAL | Text files or CSV; scrubs on import |
| `run_grading` | WRITE_LOCAL | Starts a workflow run; returns `run_id`, counts |
| `get_run_status` | READ | Progress, tokens used, flags summary |
| `review_queue` | READ | Typed items (ids, flags, levels); content rendered via `render.py` |
| `override_mark` | WRITE_LOCAL | Teacher action, with reason; points recomputed |
| `accept_proposed` | WRITE_LOCAL | Bulk-accept non-flagged judgments |
| `class_report` | READ | Deterministic counts |
| `student_profile` | READ | Verified gaps, possible gaps, evidence counts |
| `recommend_next` | READ | Section 12 |
| `draft_feedback` | WRITE_LOCAL | Template-assembled from verified judgments; creates an artifact |
| `draft_remedial` (P1) | WRITE_LOCAL | Section 15 |
| `request_release` | WRITE_LOCAL | Creates a pending approval for an artifact |
| `release_artifact` | **RELEASE** | Gated by P2 |
| `export_marks` | WRITE_LOCAL | CSV to the teacher's local folder |

**Agent system prompt** states the role, that the agent never sees student text or names, that it must use tools for everything factual, that it relays denials kindly with the next step, and that it never claims a gap, mark, or approval the tools did not return. The prompt is **not** the enforcement mechanism; P1–P8 and the information boundaries are.

---

## 14. Evaluation (this is the proof)

**Data (synthetic, committed, clearly labeled; no real students):**
- One rubric, 4 criteria, 3 levels each.
- About 30 synthetic answers with **gold levels and error tags assigned and checked by the builder** (state in the README that gold labels are one person's judgment, not a teacher panel).
- Planted cases: 6 prompt-injection submissions (instructions to the grader, fake score claims, fake system text); 4 submissions containing roster names or a classmate's name; 4 near-duplicate pairs where one has been given a different mark in the gold set.

**Metrics (report whatever is measured; do not promise numbers):**
- Level agreement with gold: exact and within one level; weighted agreement (e.g., quadratic weighted kappa).
- Error-tag accuracy (and confusion between tags).
- Evidence verification rate (share of judgments whose quotes verified) and hallucinated-quote rate.
- Review-queue precision/recall for the planted problems.
- Injection suite: share of injected submissions that obtained an unearned level; share caught by flags.
- Consistency detection recall on the planted pairs (P1).
- Cost and latency per submission; double-grading disagreement rate.

**Invariants (must be 100% by construction; any failure is a bug):**
out-of-range marks = 0; outbound requests containing roster names = 0; releases without a matching approved hash = 0; model-written approvals = 0.

**Ablation (the "not a wrapper" evidence):** run the same gold set through `eval/baseline_wrapper.py` (a single prompt: "grade this out of N and give feedback", model returns a number) and through Simo. Report both columns for: arithmetic or out-of-range errors, hallucinated evidence, injection success, PII in outbound requests, and review precision. State honestly that the dataset is small and synthetic and that results are indicative, not a validation study.

**Models:** run the eval on the OpenAI API and on one local open-weight model; report both side by side. A weaker local model scoring lower on agreement while the invariants still hold is a legitimate and defensible result.

**Record/replay:** `LLM_MODE=record` stores each call keyed by a hash of (model, messages, parameters) in `eval/cassettes/`; `replay` serves them without network. CI and judges can reproduce results offline.

---

## 15. Remedial worksheet (P1) and upstream changes

**Remedial draft:** for a student or group with a verified gap on concept C: the prerequisite-first rule applies; an LLM drafts items with answer keys and rubric levels; code verifies each item is tagged to the target concept, difficulty is non-decreasing, no item duplicates a previously used question (similarity check), and every item has a key. The result is an artifact requiring approval (P2) before release.

**Upstream changes to nanobot (list with paths and diff sizes in the README):**

| Change | Purpose | Target size |
|---|---|---|
| Policy hook at the tool-dispatch point | Allow/deny/needs-approval on every tool call | small, isolated |
| Tool profile and allowlist for `simo` | Remove shell/file/web from the teacher agent | config plus small |
| Egress guard at the provider layer | Block any model request containing roster names | small wrapper |
| Identity transform at the channel adapter | Pseudonymize inbound, re-identify outbound | small, per channel |
| Approval callback handler | Out-of-band resolution of approvals via buttons or CLI | small |
| Tool registration for new tools | Register `simo/tools.py` | small |

If any item is infeasible in a small diff (Phase 0), record the fallback and the weaker guarantee that results.

---

## 16. Agent skill (Agent Skill Open Standard)

`skills/rubric-grading/SKILL.md` with valid front matter (`name` lowercase and hyphenated, matching the folder; a clear `description`). Check required fields and limits against the **published specification and its reference validator**, not this document. Body: how to author a good rubric (discrete levels, observable descriptors, concept tags), how to interpret flags, and why the agent must not invent marks. `scripts/validate_rubric.py` is the same validator the harness uses, so the skill and harness share one source of truth. State plainly that the skill is advisory and the harness enforces.

---

## 17. Tests (pytest; the project's core claims)

LLM-dependent tests use a stub LLM or replay cassettes. A separate `scripts/smoke_llm.py` hits the real API once per path and is not part of CI.

| ID | Test |
|---|---|
| T1 | Rubric validation rejects duplicate ids, non-increasing points, unknown concepts, cyclic prerequisites |
| T2 | Scoring: level→points and totals correct; unknown level id rejected; teacher override recomputes points |
| T3 | Reader returns a numeric score instead of a level → rejected/repaired, never stored |
| T4 | Evidence: a quote not present in the submission fails verification and downgrades to review |
| T5 | Evidence: above-lowest level with zero verified quotes is never `accepted` automatically |
| T6 | Injection suite: for each planted injected submission, no unearned top level is auto-accepted; `injection_suspected` is set by code even if the reader says false |
| T7 | Quarantine: the reader call contains no tool definitions or history (assert on the outbound payload) |
| T8 | Privileged agent context never contains raw submission text (inspect messages sent to the agent model during a full run with a stub) |
| T9 | Scrubber removes roster names and variants; egress guard blocks a request containing a roster name (including one injected at the teacher chat) |
| T10 | Egress guard covers the agent's own calls, not only the reader's (via provider-layer wrapper) |
| T11 | `release_artifact` denied without approval; denied if the artifact is edited after approval (hash mismatch); denied after expiry |
| T12 | No tool or code path lets the model set `approvals.status`; callback with bad HMAC or reused nonce is rejected |
| T13 | Tool allowlist: shell, file, web tools denied (P1) |
| T14 | Static/AST test: only `rubric.py`, `verify.py`, `diagnose.py` write `judgments.points`, `status`, or `mistake_events` |
| T15 | Gap-claim gate: one event → "possible gap" plus probe; two events across two items → "verified gap" |
| T16 | `recommend_next` returns the prerequisite first when the top concept's prerequisite evidence is weaker |
| T17 | Budget and retries: run halts at `MAX_RUN_TOKENS` with partial results and clear status; no silent drops |
| T18 | Double-grading disagreement routes to review |
| T19 | Record/replay: a recorded run replays identically with the network disabled |
| T20 (P1) | Consistency: planted near-duplicate pair with divergent marks is flagged |

---

## 18. Build plan for Codex (time-boxed; adjust to available hours)

Small commits; tests green at each milestone; one branch or PR per milestone.

| # | Milestone | Acceptance | Time |
|---|---|---|---|
| M0 | Phase 0 discovery | Section 5 exit criteria | 45 min |
| M1 | `llm.py` (live/record/replay, retries, JSON repair, budget) + `egress.py` + `identity.py` + T9, T10, T19 | Offline replay works; guard blocks planted names | 75 min |
| M2 | `db`, `schemas`, `rubric` (validation and scoring) + T1, T2 | Pure-code tests green, no network | 75 min |
| M3 | `reader`, `verify`, `workflow` (grading pipeline) + T3–T8, T17, T18 | Pipeline runs on the gold set with stub and with real model | 120 min |
| M4 | `policy`, `approvals`, tool profile, hook, `tools` + T11–T14 | Denials visible in trace; approvals out-of-band | 90 min |
| M5 | `diagnose`, `render`, class report, `recommend_next` + T15, T16 | Class report and next-step recommendations from SQL only | 75 min |
| M6 | Eval harness: gold data, baseline wrapper, ablation report, model matrix | `report.py` prints the comparison table; cassettes committed | 90 min |
| M7 | Skill, README (what changed, how to run, compliance table), demo run on OpenAI API **and** one local open-weight model, recorded clip | Section 19 checklist complete | 60 min |
| M8 (P1/P2) | Consistency check, remedial worksheet, resumable runs, teacher style memory | Only if M0–M7 are done | as time allows |

Cut line: if total time is under about 8 hours, shrink the gold set to about 15 answers, skip M8 entirely, and keep M1–M4 intact, because the guarantees are the defense.

---

## 19. Demo and judging checklist

Demo (3–4 minutes, synthetic data only):
1. Import rubric and roster; import 10–15 synthetic submissions.
2. Run grading. Show the trace: reader calls, verification, a flagged injected submission going to review.
3. Show the **egress block**: the teacher types a real name; the agent sees a pseudonym; a deliberately planted name in a payload is blocked.
4. Teacher accepts and overrides a mark; show points recomputed in code.
5. Class report and `recommend_next`: a verified gap versus a "possible gap, here is a probe".
6. Draft feedback; request release; show the **denial** without approval, then approval via button, then an **edit that voids the approval**.
7. Show the ablation table: baseline wrapper versus Simo.
8. Show the same flow on a local open-weight model.

Judge questions to prepare for:
- *Isn't this an LLM wrapper?* → section 2 table; the ablation; the invariants.
- *What if the model is wrong?* → bounded levels, verified evidence, double-grading, review queue, teacher final.
- *What about prompt injection from students?* → quarantine, bounded blast radius, T6–T8, attack suite results.
- *How do you know it is accurate?* → gold-set agreement, stated limits (synthetic, one labeler, small n).
- *Why open-weight?* → student privacy: local inference keeps data on the teacher's machine; OpenAI API is the convenient demo option; both results are reported.
- *What did you change in nanobot?* → the section 15 table with real diff sizes.
- *Minors' data?* → pseudonymization, local storage, egress guard, no real data in the repo, data export and delete commands (P1).

---

## 20. Working rules for Codex

1. Read before writing. Never guess nanobot APIs; cite file paths in `DISCOVERY.md`.
2. Keep upstream edits minimal and isolated; new logic in `simo/`.
3. No features outside section 1. No new dependencies without a stated reason in the commit message.
4. Run the full test suite before every commit. Never mark a milestone done with failing or skipped tests.
5. Never put secrets, student text, or real names in logs, traces, commits, or the README. `TRACE_INCLUDE_TEXT=false` by default.
6. If a guarantee cannot be met as written, stop, explain, and propose the smallest alternative. Never silently weaken a guarantee or a test.
7. Keep the README current: setup, config for OpenAI and local models, running tests and the eval, the trace viewer, the upstream-changes table with real diff sizes, license, limitations.

---

## 21. Limitations to state honestly

- Grading and diagnosis rely on a model and can be wrong; the design bounds and surfaces errors, it does not eliminate them.
- The gold set is synthetic and labeled by one person; no study with real teachers or students was run.
- Name scrubbing is roster-based; unlisted names and indirect identifiers can slip through. The egress guard only blocks what it knows.
- Heuristic injection detection is best-effort; the real protection is quarantine and bounded effect.
- Typed text only; no handwriting, diagrams, or math-heavy symbolic answers.
- Consistency checks use simple text similarity and will miss paraphrases.
- Small local models may need larger sizes or looser prompts; report those results as measured.
- If Phase 0 forced any fallback (no channel transform, no buttons, no out-of-agent rendering), the corresponding guarantee is weaker and must be described as such.