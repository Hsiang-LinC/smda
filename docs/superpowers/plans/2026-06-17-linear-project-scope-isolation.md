# Linear Project Scope Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope the Linear backlog adapter's issue scan and child creation to a single Linear project, so multiple SMDA-managed repos can share one Linear team without cross-dispatching each other's work.

**Architecture:** Add an optional `project_id` to `LinearBacklogAdapter`. When set, it is applied as a `project: { id: { eq } }` filter in `list_issues` and as `projectId` on `create_child` input. The id is sourced from `SMDA_LINEAR_PROJECT_ID` in the environment (matching the existing `SMDA_LINEAR_TEAM_ID` pattern); the config `scope_id` stays a human-readable reference, with a warning when it is declared but the env id is absent.

**Tech Stack:** Python 3.12+, stdlib only (`urllib`, `warnings`), pytest. Linear GraphQL.

## Global Constraints

- `project_id` is OPTIONAL; unset must preserve today's exact behavior (no project filter, no `projectId` stamp). Existing tests that assert exact GraphQL variables must keep passing unchanged.
- Project id is sourced from env `SMDA_LINEAR_PROJECT_ID` (a Linear project UUID), not from the config slug.
- Filter by Linear project **id** (`project: { id: { eq } }`), not slug.
- Both halves ship together: scan filter AND `create_child` `projectId` stamp. Filtering alone would hide engine-published children.
- No new dependencies. Quality gate: `uv run --project . pytest packages/scheduler/tests -q` green.

---

### Task 1: Adapter accepts `project_id` and applies it to `list_issues`

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/linear_backlog.py` (`LinearBacklogAdapter.__init__` ~50-61; `list_issues` ~148-182)
- Test: `packages/scheduler/tests/test_linear_backlog.py`

**Interfaces:**
- Produces: `LinearBacklogAdapter(..., project_id: str | None = None)`; when `project_id` is set, `list_issues` adds `filter["project"] = {"id": {"eq": project_id}}`.

- [ ] **Step 1: Write the failing test**

```python
def test_linear_backlog_list_issues_scopes_to_project_when_configured():
    transport = RecordingTransport(
        [{"data": {"team": {"issues": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
        project_id="proj-A",
    )

    adapter.list_issues(state="Todo", label="agent", parent_id=None, limit=25, cursor=None)

    assert transport.calls[0][1]["filter"] == {
        "state": {"name": {"eq": "Todo"}},
        "labels": {"name": {"eq": "agent"}},
        "project": {"id": {"eq": "proj-A"}},
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project . pytest packages/scheduler/tests/test_linear_backlog.py::test_linear_backlog_list_issues_scopes_to_project_when_configured -v`
Expected: FAIL — `__init__` got an unexpected keyword argument `project_id` (or filter lacks `project`).

- [ ] **Step 3: Write minimal implementation**

In `__init__`, add the parameter and store it:

```python
    def __init__(
        self,
        *,
        transport: GraphQLTransport,
        team_id: str,
        state_ids: dict[str, str],
        label_ids: dict[str, str] | None = None,
        project_id: str | None = None,
    ) -> None:
        self._transport = transport
        self._team_id = team_id
        self._state_ids = dict(state_ids)
        self._label_ids = dict(label_ids or {})
        self._project_id = project_id
```

In `list_issues`, add the project filter before the parent clause:

```python
        filter_input: dict[str, Any] = {
            "state": {"name": {"eq": state}},
            "labels": {"name": {"eq": label}},
        }
        if self._project_id is not None:
            filter_input["project"] = {"id": {"eq": self._project_id}}
        if parent_id is not None:
            filter_input["parent"] = {"id": {"eq": parent_id}}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --project . pytest packages/scheduler/tests/test_linear_backlog.py -q`
Expected: PASS — the new test passes and `test_linear_backlog_lists_filtered_issues_with_pagination` (no `project_id`) still passes (filter unchanged).

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/linear_backlog.py packages/scheduler/tests/test_linear_backlog.py
git commit -m "feat: scope Linear list_issues to a project when configured"
```

---

### Task 2: `create_child` stamps `projectId` when configured

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/linear_backlog.py` (`create_child` ~113-146)
- Test: `packages/scheduler/tests/test_linear_backlog.py`

**Interfaces:**
- Consumes: `self._project_id` from Task 1.
- Produces: `create_child` includes `input["projectId"] = project_id` when set, so created children fall inside the scanned project.

- [ ] **Step 1: Write the failing test**

```python
def test_linear_backlog_create_child_stamps_project_when_configured():
    transport = RecordingTransport(
        [
            {
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {
                            "id": "uuid-2",
                            "identifier": "LIN-2",
                            "title": "Child",
                            "description": "Context packet",
                            "state": {"name": "Todo"},
                            "parent": {"identifier": "LIN-1"},
                        },
                    }
                }
            }
        ]
    )
    adapter = LinearBacklogAdapter(
        transport=transport,
        team_id="team-1",
        state_ids={},
        project_id="proj-A",
    )

    adapter.create_child(parent_id="LIN-1", title="Child", body="Context packet")

    assert transport.calls[0][1] == {
        "input": {
            "teamId": "team-1",
            "parentId": "LIN-1",
            "title": "Child",
            "description": "Context packet",
            "projectId": "proj-A",
        }
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project . pytest packages/scheduler/tests/test_linear_backlog.py::test_linear_backlog_create_child_stamps_project_when_configured -v`
Expected: FAIL — input dict has no `projectId`.

- [ ] **Step 3: Write minimal implementation**

In `create_child`, add the project stamp after the base payload, before the labels block:

```python
        input_payload: dict[str, Any] = {
            "teamId": self._team_id,
            "parentId": parent_id,
            "title": title,
            "description": body,
        }
        if self._project_id is not None:
            input_payload["projectId"] = self._project_id
        if labels:
            try:
                input_payload["labelIds"] = sorted(
                    self._label_ids[label] for label in labels
                )
            except KeyError as error:
                raise BacklogError(
                    f"Linear label is not configured: {error.args[0]}"
                ) from error
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --project . pytest packages/scheduler/tests/test_linear_backlog.py -q`
Expected: PASS — new test passes; existing `create_child` tests (no `project_id`) still pass (no `projectId` key).

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/linear_backlog.py packages/scheduler/tests/test_linear_backlog.py
git commit -m "feat: stamp projectId on created children when configured"
```

---

### Task 3: `build_linear_backlog_adapter` reads `SMDA_LINEAR_PROJECT_ID`

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/linear_backlog.py` (`build_linear_backlog_adapter` ~253-266)
- Test: `packages/scheduler/tests/test_linear_backlog.py`

**Interfaces:**
- Consumes: `LinearBacklogAdapter(project_id=...)` from Task 1.
- Produces: `build_linear_backlog_adapter` threads `env["SMDA_LINEAR_PROJECT_ID"]` (optional) into the adapter.

- [ ] **Step 1: Write the failing test**

```python
def test_build_linear_backlog_adapter_threads_project_id():
    transport_calls = []

    def urlopen(request, timeout):
        transport_calls.append(request)
        return FakeHttpResponse(
            b'{"data": {"team": {"issues": {"nodes": [], "pageInfo": {"hasNextPage": false, "endCursor": null}}}}}'
        )

    adapter = build_linear_backlog_adapter(
        env={
            "LINEAR_API_KEY": "lin_api_test",
            "SMDA_LINEAR_TEAM_ID": "team-1",
            "SMDA_LINEAR_STATE_TODO": "state-todo",
            "SMDA_LINEAR_PROJECT_ID": "proj-A",
        },
        urlopen=urlopen,
    )

    adapter.list_issues(state="Todo", label="agent", parent_id=None)

    assert b'"project": {"id": {"eq": "proj-A"}}' in transport_calls[0].data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project . pytest packages/scheduler/tests/test_linear_backlog.py::test_build_linear_backlog_adapter_threads_project_id -v`
Expected: FAIL — project filter absent from the request body.

- [ ] **Step 3: Write minimal implementation**

```python
def build_linear_backlog_adapter(
    *,
    env: dict[str, str],
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> LinearBacklogAdapter:
    api_key = _required_env(env, "LINEAR_API_KEY")
    team_id = _required_env(env, "SMDA_LINEAR_TEAM_ID")
    state_ids = _state_ids_from_env(env)
    project_id = env.get("SMDA_LINEAR_PROJECT_ID") or None
    return LinearBacklogAdapter(
        transport=LinearHttpTransport(api_key=api_key, urlopen=urlopen),
        team_id=team_id,
        state_ids=state_ids,
        label_ids=_label_ids_from_env(env),
        project_id=project_id,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --project . pytest packages/scheduler/tests/test_linear_backlog.py -q`
Expected: PASS — new test passes; `test_build_linear_backlog_adapter_uses_environment_configuration` (no project env) still passes.

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/linear_backlog.py packages/scheduler/tests/test_linear_backlog.py
git commit -m "feat: read SMDA_LINEAR_PROJECT_ID into the Linear adapter"
```

---

### Task 4: Warn when config `scope_id` is declared but the project env id is absent

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/linear_backlog.py` (add `import warnings` near top ~3-6; `build_linear_backlog_adapter` signature + body)
- Modify: `packages/scheduler/src/smda_scheduler/cli.py` (`_build_live_daemon_tick`, the `build_linear_backlog_adapter(env=dict(os.environ))` call ~200)
- Test: `packages/scheduler/tests/test_linear_backlog.py`

**Interfaces:**
- Produces: `build_linear_backlog_adapter(..., declared_scope_id: str | None = None)`; warns via `warnings.warn` when `declared_scope_id` is truthy and `SMDA_LINEAR_PROJECT_ID` is unset.
- Consumes (cli): `config.adapters.backlog.scope_id`.

- [ ] **Step 1: Write the failing test**

```python
import warnings

def test_build_linear_backlog_adapter_warns_when_scope_declared_without_project_env():
    def urlopen(request, timeout):
        return FakeHttpResponse(b'{"data": {}}')

    with pytest.warns(UserWarning, match="SMDA_LINEAR_PROJECT_ID"):
        build_linear_backlog_adapter(
            env={
                "LINEAR_API_KEY": "lin_api_test",
                "SMDA_LINEAR_TEAM_ID": "team-1",
                "SMDA_LINEAR_STATE_TODO": "state-todo",
            },
            urlopen=urlopen,
            declared_scope_id="trading-advisor-41f010901151",
        )


def test_build_linear_backlog_adapter_no_warning_when_project_env_present():
    def urlopen(request, timeout):
        return FakeHttpResponse(b'{"data": {}}')

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        build_linear_backlog_adapter(
            env={
                "LINEAR_API_KEY": "lin_api_test",
                "SMDA_LINEAR_TEAM_ID": "team-1",
                "SMDA_LINEAR_STATE_TODO": "state-todo",
                "SMDA_LINEAR_PROJECT_ID": "proj-A",
            },
            urlopen=urlopen,
            declared_scope_id="trading-advisor-41f010901151",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project . pytest packages/scheduler/tests/test_linear_backlog.py -k "warns_when_scope or no_warning_when_project" -v`
Expected: FAIL — `declared_scope_id` is an unexpected keyword argument.

- [ ] **Step 3: Write minimal implementation**

Add `import warnings` to the imports block. Then:

```python
def build_linear_backlog_adapter(
    *,
    env: dict[str, str],
    urlopen: Callable[..., Any] = urllib.request.urlopen,
    declared_scope_id: str | None = None,
) -> LinearBacklogAdapter:
    api_key = _required_env(env, "LINEAR_API_KEY")
    team_id = _required_env(env, "SMDA_LINEAR_TEAM_ID")
    state_ids = _state_ids_from_env(env)
    project_id = env.get("SMDA_LINEAR_PROJECT_ID") or None
    if declared_scope_id and not project_id:
        warnings.warn(
            "smda.config backlog.scope_id is set but SMDA_LINEAR_PROJECT_ID is "
            "unset; the live query will not scope to a project, so issues are not "
            "isolated from other repos sharing this team.",
            stacklevel=2,
        )
    return LinearBacklogAdapter(
        transport=LinearHttpTransport(api_key=api_key, urlopen=urlopen),
        team_id=team_id,
        state_ids=state_ids,
        label_ids=_label_ids_from_env(env),
        project_id=project_id,
    )
```

In `cli.py` `_build_live_daemon_tick`, pass the declared scope id:

```python
        backlog=build_linear_backlog_adapter(
            env=dict(os.environ),
            declared_scope_id=config.adapters.backlog.scope_id,
        ),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --project . pytest packages/scheduler/tests -q`
Expected: PASS — warning tests pass; full suite (incl. `test_cli.py`) green.

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/linear_backlog.py packages/scheduler/src/smda_scheduler/cli.py packages/scheduler/tests/test_linear_backlog.py
git commit -m "feat: warn when Linear scope_id is declared without SMDA_LINEAR_PROJECT_ID"
```

---

### Task 5: Update setup-smda-automation env contract docs

**Files:**
- Modify: `plugins/smda-automation/skills/setup-smda-automation/daemon-operations.md` (§ 1 env list)
- Modify: `plugins/smda-automation/skills/setup-smda-automation/adapters.md` (Linear env block)
- Modify: `docs/work-ledger/follow-ups.md` (`linear-scope-id-ignored` → resolved-by note)

**Interfaces:** docs only; no code.

- [ ] **Step 1: Add `SMDA_LINEAR_PROJECT_ID` to the env contract**

In `daemon-operations.md` § 1, add to the env list:

```markdown
- `SMDA_LINEAR_PROJECT_ID` — optional Linear project UUID. Set it to scope the
  scan and child creation to one project so multiple SMDA-managed repos can
  share a team without cross-dispatching. Fetch it read-only like the team id.
  Recommended as the multi-repo isolation default.
```

In `adapters.md`, after the state/label env lines, note that `SMDA_LINEAR_PROJECT_ID` enables project-per-repo isolation and that `scope_id` in config is the human reference for it.

- [ ] **Step 2: Mark the follow-up resolved**

In `docs/work-ledger/follow-ups.md`, set `linear-scope-id-ignored` status to `done` once the code tasks land, with `next:` pointing at the implementing commits, and add a `completed.md` entry per tracker.md § Archive Policy.

- [ ] **Step 3: Commit**

```bash
git add plugins/smda-automation/skills/setup-smda-automation/daemon-operations.md plugins/smda-automation/skills/setup-smda-automation/adapters.md docs/work-ledger/follow-ups.md docs/work-ledger/completed.md
git commit -m "docs: add SMDA_LINEAR_PROJECT_ID to setup env contract; close scope_id follow-up"
```

---

## Notes on verification scope

Unit tests assert that the project filter and `projectId` are present in the
GraphQL variables/body — the actual issue filtering happens server-side in
Linear. End-to-end isolation (repo A's daemon never returning repo B's issues)
is proven by the live Linear smoke (`gap-2-live-linear-smoke`), which is a
separate opt-in run gated on credentials; extend it to assert project-scoped
listing when picking this up against a real project.
