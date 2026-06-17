# Phase 2 — Methodology Skill Injection Implementation Plan

> **REQUIRED SUB-SKILL:** `superpowers:executing-plans` + `tdd`. Red → green →
> refactor, one task at a time.

> **Agent handoff (read first — hand-rolled RepoContextPacket):**
> - **Branch:** work on `target-c`. Do NOT branch from `master`/`main`.
> - **Read first:** [CONTEXT.md](../../CONTEXT.md),
>   [ADR-0004](../../adr/0004-roles-bind-methodology-skills.md),
>   [target-C spec](../specs/2026-06-16-target-c-modular-parallel-engine.md) §3.
> - **Line numbers are indicative** — grep for the named symbols; never trust a
>   bare line number.
> - **Prereqs:** Phase 1 (engine) landed. Independent of Phase 0, but Phase 0's
>   schema artifact is unaffected.
> - **Discipline:** TDD red→green. Parity = do NOT change existing test
>   assertions. `uv run pytest packages/scheduler/tests/`, `npm run test:ts`,
>   `npx tsc --noEmit` green before "done". This phase is **Python-only** — the
>   runner passes the prompt through unchanged.

**Goal:** Bind a methodology skill (e.g. `tdd`, `to-issues`, `diagnose`) to each
`RoleContract` and have the runner **inject** that skill's content into the role
attempt prompt, so decompose/implement/review/fix behaviour follows a versioned
methodology instead of the model's per-turn improvisation. Implements
[ADR-0004](../../adr/0004-roles-bind-methodology-skills.md); skill provenance is
the consumer repo's configured `skills_dir` (Q11).

**Design (back-compat + opt-in):** `config.context.skills_dir` is optional. When
unset, nothing changes (current behaviour, all existing tests pass). When set,
`build_repo_packet` loads every skill any role declares into
`RepoContextPacket.skills` (fail-closed: a declared-but-missing skill is a context
error), and the three prompt helpers append the declared methodology to the
rendered prompt.

**Architecture:** Injection happens in the centralized prompt helpers
(`role_attempts._prompt` / `_parent_graph_prompt` / `_parent_prompt`,
~`role_attempts.py:335-387`) — the single choke point where `render_prompt` is
called. No request-builder or runner change.

**Tech Stack:** Python scheduler package, pytest.

## Relationship To Other Plans

- Phase 2 of
  [target-c-implementation-path](2026-06-16-target-c-implementation-path.md).
- Spec §3; [ADR-0004](../../adr/0004-roles-bind-methodology-skills.md).
- The roadmap_decomposer role added in Phase 3 will declare `to-prd`/`to-issues`
  and ride this mechanism for free.

## Scope

In scope:
- `RoleContract.methodology_skills: tuple[str, ...]` + the initial role→skill
  bindings (ADR-0004 table).
- A skill loader: resolve `<skills_dir>/<skill_id>/SKILL.md` (marketplace
  layout), strip frontmatter, return the methodology body.
- `config.context.skills_dir` (optional).
- `RepoContextPacket.skills: Mapping[str, str]` + `build_repo_packet` loading
  declared skills, fail-closed on a missing declared skill.
- Inject methodology in the three prompt helpers (no-op when `skills` empty).

Out of scope:
- Distilling/truncating large skills to a token budget (v1 injects the whole
  SKILL.md body; note it as a follow-up if prompts blow the budget).
- Per-role model-tier selection.
- Provisioning skills into the consumer repo (that is `setup-smda-automation`'s
  job; this phase only *consumes* `skills_dir`).

## File Structure

- Modify `role_contracts.py` (`methodology_skills` field + bindings).
- Create `skill_loader.py` (resolve + read + strip frontmatter).
- Modify `config.py` (`skills_dir` on the context config).
- Modify `context_packets.py` (`RepoContextPacket.skills`; load in
  `build_repo_packet`; fail-closed).
- Modify `role_attempts.py` (inject methodology in the prompt helpers).
- Tests: `test_role_contracts.py`, `test_skill_loader.py`,
  `test_context_packets.py`, `test_role_attempts.py`.

---

## Task 1: `RoleContract.methodology_skills` + bindings

- [ ] **Step 1: Failing test** (`test_role_contracts.py`): the child implementer
  contract declares `tdd`; the graph decomposer declares `to-issues`.

```python
from smda_scheduler.role_contracts import (
    CHILD_ROLE_BY_PHASE, PARENT_ROLE_BY_PHASE,
)
from smda_scheduler.workflow import ChildPhase, ParentPhase

def test_child_implementer_binds_tdd():
    assert "tdd" in CHILD_ROLE_BY_PHASE[ChildPhase.IMPLEMENTING].methodology_skills

def test_graph_decomposer_binds_to_issues():
    # decomposer is keyed under the decompose phase contract
    contract = PARENT_ROLE_BY_PHASE[ParentPhase.GRAPH_DECOMPOSING]
    assert "to-issues" in contract.methodology_skills
```

- [ ] **Step 2: Implement** — add `methodology_skills: tuple[str, ...] = ()` to
  `RoleContract`; set it on each contract per the ADR-0004 table (implementer→tdd,
  decomposer→to-issues, fixers→diagnose, quality reviewer→improve-codebase-
  architecture, spec reviewers→grill-with-docs/triage, parent_qa→triage). Verify
  the exact registry keys against `role_contracts.py`.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 2: Skill loader

**Files:** `skill_loader.py`; `test_skill_loader.py`.

- [ ] **Step 1: Failing tests** — load a skill body from
  `<skills_dir>/tdd/SKILL.md`, frontmatter stripped; missing skill raises.

```python
def test_loads_skill_body_stripping_frontmatter(tmp_path):
    skill = tmp_path / "tdd" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: tdd\n---\n\n# TDD\nRed green refactor.\n")
    body = load_skill_methodology(tmp_path, "tdd")
    assert "Red green refactor." in body
    assert "name: tdd" not in body

def test_missing_skill_raises(tmp_path):
    with pytest.raises(SkillNotFoundError):
        load_skill_methodology(tmp_path, "nope")
```

- [ ] **Step 2: Implement** `skill_loader.py`:

```python
def load_skill_methodology(skills_dir: Path, skill_id: str) -> str:
    candidates = [skills_dir / skill_id / "SKILL.md", skills_dir / f"{skill_id}.md"]
    for path in candidates:
        if path.exists():
            return _strip_frontmatter(path.read_text(encoding="utf-8")).strip()
    raise SkillNotFoundError(skill_id)
```

`_strip_frontmatter` removes a leading `---\n…\n---\n` block if present.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 3: `skills_dir` config + `RepoContextPacket.skills` (fail-closed)

**Files:** `config.py`, `context_packets.py`; `test_context_packets.py`.

- [ ] **Step 1: Failing tests** — with `skills_dir` configured + a skill present,
  `build_repo_packet().skills` contains the declared skill bodies; with
  `skills_dir` set but a declared skill missing, `build_repo_packet` raises
  `ContextDiscoveryError`; with `skills_dir` unset, `skills == {}`.

- [ ] **Step 2: Implement**
  - Add optional `skills_dir` to the context config (`config.py`).
  - Add `skills: Mapping[str, str] = field(default_factory=dict)` to
    `RepoContextPacket` (frozen-safe default).
  - In `build_repo_packet`: if `skills_dir` set, collect the declared skill ids
    from all role contracts (`{s for c in [*CHILD_ROLE_BY_PHASE.values(),
    *PARENT_ROLE_BY_PHASE.values()] for s in c.methodology_skills}`), load each via
    `load_skill_methodology` (resolved under repo_root), and fail closed on
    `SkillNotFoundError` → `ContextDiscoveryError`. When unset, leave `skills={}`.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 4: Inject methodology into the prompt helpers

**Files:** `role_attempts.py`; `test_role_attempts.py`.

- [ ] **Step 1: Failing test** — a built request's prompt contains the bound
  methodology text when `repo_context.skills` has it; and is **unchanged** when
  `skills == {}` (back-compat).

```python
def test_prompt_injects_bound_methodology_when_present(...):
    repo_context = RepoContextPacket(..., skills={"tdd": "Red green refactor."})
    request = build_child_role_attempt_request(..., phase=ChildPhase.IMPLEMENTING, ...)
    assert "Red green refactor." in request.prompt

def test_prompt_unchanged_when_no_skills(...):
    # skills defaults to {} -> identical prompt to today
```

- [ ] **Step 2: Implement** a helper and call it from `_prompt`,
  `_parent_graph_prompt`, `_parent_prompt`:

```python
def _inject_methodology(prompt: str, contract: RoleContract, skills: Mapping[str, str]) -> str:
    blocks = [
        f"\n\n## Methodology: {skill_id}\n{skills[skill_id]}"
        for skill_id in contract.methodology_skills
        if skill_id in skills
    ]
    return prompt + "".join(blocks)
```

Thread `repo_context.skills` into the three helpers (they currently receive
`bootloader_text`; pass `skills` too, or pass `repo_context`). Keep signatures
minimal; default to `{}` so non-injecting callers are unaffected.

- [ ] **Step 3: Run, green. Commit.**

---

## Task 5: Full gate

- [ ] `uv run pytest packages/scheduler/tests/ -q` ; `npm run test:ts` ;
  `npx tsc --noEmit`. All green.
- [ ] Confirm: with no `skills_dir`, prompts are byte-identical to pre-Phase-2
  (the back-compat assertion).
- [ ] Commit.

## Acceptance Criteria

1. Each role contract declares its methodology skill(s) per ADR-0004.
2. With `skills_dir` configured, a role attempt's prompt contains its bound
   methodology; a declared-but-missing skill fails closed at context build.
3. With `skills_dir` unset, behaviour + prompts are unchanged (existing tests
   pass untouched).
4. The runner/TS is unchanged (prompt passes through).
5. Full suite + TS + tsc green.

## Done Definition

- Methodology is data (declared per role) + injected deterministically; the agent
  does not self-select. New roles (Phase 3 roadmap_decomposer) declare a skill and
  inherit injection for free.
- Skill provenance is the consumer repo's `skills_dir`; tests inject a fake dir.

## Out Of Scope — Later

- Token-budget distillation of large skills (inject a section, not the whole
  file) — add only if prompts overflow in practice.
