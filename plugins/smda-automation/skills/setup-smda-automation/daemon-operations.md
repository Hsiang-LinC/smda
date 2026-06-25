# SMDA Daemon Operations

Optional, approval-gated Tier-3 artifacts for running the SMDA Scheduler daemon
against a configured target repo. Everything here is **ops glue that invokes the
product CLI** — it must not reimplement scanner, routing, or phase-machine logic
(that is product code; see Hard Gate 7 in SKILL.md). Write these only when the
user explicitly asks to operate the daemon, and never start a live loop during
setup or refresh.

## 1. Populate the Linear adapter environment

The backlog adapter reads credentials and IDs from the process environment, not
from committed config (see [adapters.md](adapters.md)). A fresh setup must put
these into a gitignored local env file (e.g. `.env`):

- `LINEAR_API_KEY` — secret.
- `SMDA_LINEAR_TEAM_ID` — the Linear team UUID.
- `SMDA_LINEAR_PROJECT_ID` — optional Linear project UUID. When set, the adapter
  scopes both the issue scan and child creation to that project, so multiple
  SMDA-managed repos can share one team without cross-dispatching each other's
  work. This is the recommended multi-repo isolation default
  (`config.adapters.backlog.scope_id` is the human reference for it); unset means
  team-wide scanning, which is unsafe when repos share a team. **One project per
  repo.** If the repo's project already exists, fetch its id read-only (query
  below). If it does not, creating it is a **live tracker mutation** — confirm
  with the user first, like creating states/labels (§ end of this section), then
  fetch the new id.
- `SMDA_LINEAR_STATE_<NAME>` — one per tracker state the phase machine drives
  (at minimum `TODO`; in practice the full set the tracker contract uses:
  `TODO`, `IN_PROGRESS`, `AGENT_REVIEW`, `HUMAN_REVIEW`, `BLOCKED`, `DONE`,
  `CANCELED`). The env-var suffix maps to a Linear state name via
  `suffix.replace("_"," ").title()` — so `SMDA_LINEAR_STATE_IN_PROGRESS` →
  state `In Progress`. The value is the state's UUID.
- `SMDA_LINEAR_LABEL_<NAME>` — label UUIDs the engine reads/writes. The suffix
  maps via `suffix.lower().replace("_","-")`. The engine programmatically stamps
  only the actor label (`agent`); execution modes (`Execution: smda` /
  `Execution: smda-child`) are **issue body markers, not labels**, so they need
  no label entry.

The team/state/label UUIDs can be fetched **read-only** with the user's existing
key — this is inspection, not a live tracker mutation, but still confirm before
sending any request to the tracker. Example (Linear GraphQL):

```bash
# Authorization header takes the raw personal API key (no "Bearer").
# 1) teams -> pick the team id
curl -s https://api.linear.app/graphql -H "Authorization: $LINEAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ teams(first:50){ nodes{ id key name } } }"}'

# 2) states + labels for that team id
curl -s https://api.linear.app/graphql -H "Authorization: $LINEAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"query($id:String!){ team(id:$id){ states(first:50){nodes{id name type}} labels(first:100){nodes{id name}} } }","variables":{"id":"<TEAM_ID>"}}'

# 3) projects on that team -> pick (or confirm absence of) this repo's project id
curl -s https://api.linear.app/graphql -H "Authorization: $LINEAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"query($id:String!){ team(id:$id){ projects(first:100){nodes{id name}} } }","variables":{"id":"<TEAM_ID>"}}'
```

Map the returned ids to the env-var names above and write them to the gitignored
env file. Do not create, rename, or delete tracker states/labels — that is a live
adapter mutation requiring explicit approval. Creating a Linear **project** for a
new repo is the same class of live mutation: confirm first, then create with
`projectCreate` (e.g. `mutation{ projectCreate(input:{name:"<repo>",teamIds:["<TEAM_ID>"]}){ project{ id } } }`)
and record the returned id as `SMDA_LINEAR_PROJECT_ID`.

**Onboarding additional repos to an existing team (multi-repo).** States and
labels are team-scoped, so their ids are identical across every repo on that
team. Only the project differs. Shortcut: copy the `SMDA_LINEAR_TEAM_ID`,
`SMDA_LINEAR_STATE_*`, and `SMDA_LINEAR_LABEL_*` lines verbatim from the template
repo's env, then set just `SMDA_LINEAR_PROJECT_ID` to the new repo's project id
and `config.adapters.backlog.scope_id` to a distinct human reference for it. No
need to re-fetch states/labels per repo.

Validate config + context before any run:

```bash
uv run --project <smda-product-root> smda-scheduler validate-config <config> --repo-root <repo>
uv run --project <smda-product-root> smda-scheduler validate-context <config> --repo-root <repo>
```

The execution agent is configured in committed repo config, not in the daemon
command. Keep the sandbox provider and agent selection separate:

```json
{
  "adapters": {
    "execution": {
      "id": "sandcastle",
      "version_constraint": ">=0.1.0",
      "provider": "noSandbox",
      "agent": {
        "provider": "codex",
        "model": "gpt-5-codex",
        "effort": "high"
      }
    }
  }
}
```

Use a model name and effort supported by the target repo's account. If a live
run fails because the model is unsupported, update `adapters.execution.agent`
and re-run `validate-config`; do not patch setup-generated daemon scripts or
product runner code to change the model.

## 2. Daemon invocation model

```bash
smda-scheduler daemon <config> --repo-root <repo> --state "In Progress" --state Todo \
  --label agent --owner smda-daemon --max-parallel 3
```

`--max-ticks` defaults to **1**: one tick per invocation, then exit. The engine
is intentionally not a self-driving daemon — continuous running is an external
concern. A single tick = retry pending tracker effects → scan the ordered state
set (`In Progress`, then `Todo`, so in-flight work is considered first) →
compute the eligible candidate set → dispatch up to `--max-parallel` candidates
concurrently, joined as one ThreadPool batch. `--max-ticks` still bounds the
number of ticks per invocation. New children are published into `Todo`; children
already in `Agent Review` need no scan because the parent lands them from the
ledger.

Two ways to run continuously:

- **External scheduler** (launchd/systemd/cron) re-invokes one bounded tick on a
  cadence; or
- a **controller script** that loops in the background — `start` to detach via
  `nohup`, `run` for foreground (template in § 3).

### macOS caveat (TCC)

launchd and cron jobs cannot access TCC-protected folders (`~/Desktop`,
`~/Documents`, `~/Downloads`). If the repo (or the SMDA product checkout) lives
under one of these, a launchd/cron job fails with `Operation not permitted`. An
interactive terminal already holds the Desktop grant, so use the controller
script there (`start` detaches via `nohup` and survives the terminal closing),
or move the repos out of the protected folder for a permanent fix.

## 3. Daemon controller template

A `start | stop | restart | status | run` controller that sources the env file,
survives a failing tick, detaches into the background, handles signals safely,
and enforces **one daemon per repo**. The single-daemon guard matters: two
concurrent scanners can double-dispatch a `Todo` issue in the window before its
state flips off the scan filter (parent intake has no cross-process mutex). An
atomic `mkdir` lock enforces single ownership and reclaims a lock left by a dead
holder.

Design choices worth keeping:

- **Background via `nohup` self-detach, not `setsid`** — macOS has no `setsid`
  binary. `start` re-execs `... run` under `nohup`, and the detached loop records
  its own `$$` in the lock, so startup is confirmed by polling the lock (do not
  trust `$!` of the `nohup` wrapper).
- **Safe signals** — `stop` sends `SIGTERM`; the loop forwards it to the in-flight
  tick child so an in-progress `uv run`/`sleep` is interrupted immediately (not
  after the full interval), then releases the lock on `EXIT`. Escalate to
  `SIGKILL` only after a grace window. A killed mid-tick is safe to re-run: SMDA's
  durable outbox + child claim/lease + `reconcile-claims` make ticks resumable.
- **Interruptible sleep** — run `sleep & wait` (not bare `sleep`) so a signal
  during the inter-tick sleep is handled at once; bash only runs traps between
  foreground commands.
- **One liveness marker** — the `.smda/smda-daemon-loop.lock` dir (pid inside) is
  the only liveness source; `status` reads it with `kill -0`. Do not add a second
  pidfile that can disagree with the lock.

```bash
#!/usr/bin/env bash
# SMDA Scheduler daemon controller (start/stop/restart/status) + the loop itself.
# launchd/cron cannot run this under a TCC-protected folder (~/Desktop etc.);
# start from an interactive terminal (nohup keeps it alive after the terminal
# closes). Run at most one daemon per repo. Usage:
#   smda-daemon-loop.sh start [interval_seconds]   detach the loop (default 30)
#   smda-daemon-loop.sh stop                       graceful stop (SIGTERM -> SIGKILL fallback)
#   smda-daemon-loop.sh restart [interval_seconds] stop then start
#   smda-daemon-loop.sh status                     report running / not (read-only)
#   smda-daemon-loop.sh run [interval_seconds]     run the loop in the foreground (Ctrl-C)
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
SMDA_PROJECT="<smda-product-root>"
SELF="$SCRIPT_DIR/$(basename -- "${BASH_SOURCE[0]}")"
LOCK_DIR="$REPO_ROOT/.smda/smda-daemon-loop.lock"
LOCK_PID_FILE="$LOCK_DIR/pid"
LOG_FILE="$REPO_ROOT/.smda/smda-daemon-loop.log"
STOP_GRACE=10
# Max candidates dispatched concurrently per bounded daemon tick.
MAX_PARALLEL=3

lock_holder() {
  local pid; pid="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then printf '%s\n' "$pid"; return 0; fi
  return 1
}
status_cmd() {
  local pid
  if pid="$(lock_holder)"; then printf 'running: pid %s  (lock %s)\nlog: %s\n' "$pid" "$LOCK_DIR" "$LOG_FILE"; return 0; fi
  printf 'not running\n'; [ -d "$LOCK_DIR" ] && printf 'stale lock present: %s\n' "$LOCK_DIR"; return 3
}
release_lock() { rm -rf "$LOCK_DIR"; }
acquire_lock() {
  mkdir -p "$REPO_ROOT/.smda"
  if mkdir "$LOCK_DIR" 2>/dev/null; then printf '%s\n' "$$" > "$LOCK_PID_FILE"; return 0; fi
  local other
  if other="$(lock_holder)"; then printf 'error: another SMDA daemon is already running (pid %s)\n' "$other" >&2; exit 3; fi
  other="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
  printf 'reclaiming stale lock from pid %s\n' "${other:-unknown}" >&2
  rm -rf "$LOCK_DIR"; mkdir "$LOCK_DIR" 2>/dev/null || { printf 'error: cannot acquire lock\n' >&2; exit 3; }
  printf '%s\n' "$$" > "$LOCK_PID_FILE"
}
run_loop() {
  local interval="$1"; cd "$REPO_ROOT"
  set -a; [ -f "$REPO_ROOT/.env" ] && . "$REPO_ROOT/.env"; set +a
  acquire_lock; trap 'release_lock' EXIT
  local stop=0 child=
  on_term() { stop=1; [ -n "$child" ] && kill -TERM "$child" 2>/dev/null || true; }
  trap on_term INT TERM
  printf 'SMDA daemon: interval=%ss  repo=%s  pid=%s\n' "$interval" "$REPO_ROOT" "$$"
  while [ "$stop" -eq 0 ]; do
    uv run --project "$SMDA_PROJECT" smda-scheduler daemon "$REPO_ROOT/smda.config.json" \
      --repo-root "$REPO_ROOT" --state "In Progress" --state Todo \
      --label agent --owner smda-daemon --max-parallel "${MAX_PARALLEL:-3}" --max-ticks 1 &
    child=$!; wait "$child" || printf 'tick exited non-zero (or interrupted); continuing\n'; child=
    [ "$stop" -eq 1 ] && break
    sleep "$interval" & child=$!; wait "$child" 2>/dev/null || true; child=
  done
  printf 'stopped\n'
}
start_cmd() {
  local interval="${1:-30}" pid
  if pid="$(lock_holder)"; then printf 'already running: pid %s\n' "$pid" >&2; return 3; fi
  [ -d "$LOCK_DIR" ] && rm -rf "$LOCK_DIR"; mkdir -p "$REPO_ROOT/.smda"
  nohup "$SELF" run "$interval" >> "$LOG_FILE" 2>&1 < /dev/null &
  disown 2>/dev/null || true
  local i; for i in $(seq 10); do
    if pid="$(lock_holder)"; then printf 'started: pid %s  interval=%ss\nlog: %s\n' "$pid" "$interval" "$LOG_FILE"; return 0; fi
    sleep 0.3
  done
  printf 'error: daemon did not come up; check %s\n' "$LOG_FILE" >&2; return 1
}
stop_cmd() {
  local pid
  if ! pid="$(lock_holder)"; then printf 'not running\n'; [ -d "$LOCK_DIR" ] && rm -rf "$LOCK_DIR"; return 0; fi
  printf 'stopping pid %s (SIGTERM)...\n' "$pid"; kill -TERM "$pid" 2>/dev/null || true
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$STOP_GRACE" ]; then printf 'still alive; SIGKILL\n' >&2; kill -KILL "$pid" 2>/dev/null || true; sleep 1; break; fi
    sleep 1; waited=$((waited + 1))
  done
  [ -d "$LOCK_DIR" ] && release_lock; printf 'stopped\n'
}
case "${1:-}" in
  start)   shift; start_cmd "${1:-}";;
  stop)    stop_cmd;;
  restart) shift; stop_cmd; start_cmd "${1:-}";;
  status)  status_cmd; exit $?;;
  run)     shift; run_loop "${1:-30}";;
  *)       sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2;;
esac
```

Read-only subcommands (`status`) must work without acquiring the lock or loading
secrets. The bootloader status check in § 5 calls `status` only.

## 4. Operator command surface

Surface the full SMDA Scheduler CLI in the harness so a session can inspect and
control the runtime. All commands take the config + `--repo-root`:

| Command | Read/Write | Use |
|---|---|---|
| `validate-config` | read | Boot the config; report workspace id + ledger/artifact paths. |
| `validate-context` | read | Verify bootloader/spec/ADR/quality-gate paths resolve. |
| `status` | read | Full runtime state: parent runs, per-child phase/attempts/claim owner/backoff, paused parents. |
| `validate-state` | read | Terse health: workspace id + ledger path only. |
| `pause --parent <id>` | write | Pause a parent — its children are skipped on dispatch. |
| `resume --parent <id>` | write | Un-pause a parent. |
| `reconcile-claims` | write | Release expired child claims (crashed-worker leases). |
| `daemon` | live | Scan + dispatch one bounded tick; autonomous. Run via the controller (`smda-daemon-loop.sh start`), not directly. |

`status` is the first source for workflow progress. Its JSON payload reports
the local runtime ledger, including:

- `parent_runs` and `child_runs`: durable phase-machine truth;
- child attempt counts, claim owner, and backoff state;
- `paused_parent_ids`: durable pause gates;
- `tracker_effects`: tracker-projection outbox summary.

For Linear-backed repos, read `tracker_effects` before assuming Linear is stale
or authoritative:

- `pending > 0` with no errors can be normal short-lived projection lag; the
  next daemon tick retries pending effects before scanning work.
- `pending_with_errors > 0` or non-empty `recent_errors` means the product tried
  to project to Linear and the adapter reported a failure.
- `sent` counts effects already delivered to the tracker. If the local ledger
  says a child advanced but Linear has not updated yet, the ledger remains
  runtime truth until the projection state proves otherwise.

`pause`/`resume`/`reconcile-claims` mutate the ledger only (not tracker or git) —
safe operator controls. `daemon` is the one autonomous-action command; keep it
approval-gated. Surface the CLI commands in harness docs by default.

For model-driven control, the plugin bundles the SMDA Scheduler runtime and the
MCP server registration for its product-owned server:

```bash
python3 ./runtime/smda-scheduler-mcp.py
```

The MCP surface exposes only bounded operator tools:

- `smda_status`
- `smda_pause`
- `smda_resume`
- `smda_reconcile_claims`
- `smda_force_phase`

Do not expose the autonomous daemon as an MCP tool. Target repos consume the
server by installing/enabling the plugin. The setup skill must not generate the
server itself or any other runtime code (Hard Gate 7); it only configures the
target repo so the bundled tools have a valid `config_path` and `repo_root`.

For autonomous role dispatch, the bundled scheduler uses the plugin-local
Sandcastle runner artifact:

```bash
node ./runtime/js/sandcastle-runner.mjs
```

Target repos must not carry `packages/sandcastle-runner`, `node_modules`, or
other SMDA runtime dependencies. Their responsibility stays at config, harness
routing, tracker policy, and secrets.

## 5. Bootloader status checks (read-only)

The daemon is session-independent: it drains the tracker whether or not anyone
has a dev session open. So do not couple "start the daemon" to "start a dev
session". Instead, have the harness bootloader/routing tell a fresh session to
**check and report** daemon status at the start (read-only), so it is clear
whether tracker issues will be picked up:

```bash
<repo>/docs/harness/smda-daemon-loop.sh status   # reports running / not; read-only
```

When the user asks whether SMDA or Linear is "stuck", have the harness also
point to the product status command:

```bash
uv run --project <smda-product-root> smda-scheduler status <repo>/smda.config.json --repo-root <repo>
```

Report both surfaces separately:

- daemon controller status = process liveness;
- `smda-scheduler status` = local workflow truth plus tracker projection
  outbox;
- Linear = human-visible projection target, which may lag until pending effects
  are retried and marked sent.

The bootloader must **not auto-start** the daemon — starting an autonomous,
auto-merging loop requires explicit human approval (see adapters.md). If it is
down and the user wants autonomous dispatch, offer to start it; the user runs
`smda-daemon-loop.sh start` from a terminal. Put this pointer in the harness routing (e.g.
`docs/harness/index.md`), not duplicated in the bootloader file.

## 6. Concurrency contract

Re-dispatch safety holds **per repo for a single daemon process**: the tracker
state transition off the scan filter, the ledger parent-run (resume not
restart), durable idempotent tracker effects, child claim+lease, and sequential
ticks together prevent double work. There is no cross-process mutex on the
parent intake scan, so the single-daemon guard above is the safeguard against
running two schedulers against the same repo.
