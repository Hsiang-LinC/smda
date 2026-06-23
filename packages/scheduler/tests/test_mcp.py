import json
from io import BytesIO
from pathlib import Path

from helpers import write_minimal_config
from smda_scheduler.config import derive_workspace_paths, load_config
from smda_scheduler.mcp_server import handle_request, run_stdio_server
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.scheduling import ChildRunState, SchedulerState
from smda_scheduler.workflow import ChildPhase


def test_mcp_lists_operator_tools_without_daemon():
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response["id"] == 1
    tools = {tool["name"]: tool for tool in response["result"]["tools"]}
    assert set(tools) == {
        "smda_status",
        "smda_pause",
        "smda_resume",
        "smda_reconcile_claims",
        "smda_force_phase",
    }
    assert "smda_daemon" not in tools


def test_mcp_status_tool_returns_cli_payload(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )

    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "smda_status",
                "arguments": {
                    "config_path": str(config_path),
                    "repo_root": str(tmp_path),
                },
            },
        }
    )

    assert response["id"] == 2
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["status"] == "ok"
    assert payload["parent_runs"] == []
    assert response["result"].get("isError") is not True


def test_mcp_mutating_tools_call_existing_cli_handlers(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )

    paused = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "smda_pause",
                "arguments": {
                    "config_path": str(config_path),
                    "repo_root": str(tmp_path),
                    "parent": "DANNY-66",
                },
            },
        }
    )
    resumed = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "smda_resume",
                "arguments": {
                    "config_path": str(config_path),
                    "repo_root": str(tmp_path),
                    "parent": "DANNY-66",
                },
            },
        }
    )

    assert json.loads(paused["result"]["content"][0]["text"])["paused"] is True
    assert json.loads(resumed["result"]["content"][0]["text"])["paused"] is False


def test_mcp_reconcile_and_force_phase_call_existing_cli_handlers(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    write_minimal_config(
        config_path,
        execution_id="sandcastle",
        backlog_id="linear",
        context_id="codex-harness",
    )
    workspace = derive_workspace_paths(load_config(config_path, repo_root=tmp_path))
    ledger = PhaseLedger(workspace.ledger_path)
    ledger.save_scheduler_state(
        SchedulerState(
            children={
                "child-001": ChildRunState(
                    phase=ChildPhase.HUMAN_REVIEW_REQUIRED,
                    attempts=1,
                )
            }
        )
    )

    reconciled = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "smda_reconcile_claims",
                "arguments": {
                    "config_path": str(config_path),
                    "repo_root": str(tmp_path),
                },
            },
        }
    )
    forced = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "smda_force_phase",
                "arguments": {
                    "config_path": str(config_path),
                    "repo_root": str(tmp_path),
                    "target_kind": "child",
                    "target_id": "child-001",
                    "phase": ChildPhase.IMPLEMENTING.value,
                },
            },
        }
    )

    assert json.loads(reconciled["result"]["content"][0]["text"]) == {
        "status": "ok",
        "reset_child_ids": [],
    }
    assert json.loads(forced["result"]["content"][0]["text"])["phase"] == (
        ChildPhase.IMPLEMENTING.value
    )
    assert PhaseLedger(workspace.ledger_path).load_scheduler_state().children[
        "child-001"
    ].phase == ChildPhase.IMPLEMENTING


def test_mcp_stdio_server_handles_initialize_frame():
    request = json.dumps(
        {"jsonrpc": "2.0", "id": 5, "method": "initialize"},
        separators=(",", ":"),
    ).encode("utf-8")
    stdin = BytesIO(
        b"Content-Length: " + str(len(request)).encode() + b"\r\n\r\n" + request
    )
    stdout = BytesIO()

    run_stdio_server(stdin=stdin, stdout=stdout)

    _, body = stdout.getvalue().split(b"\r\n\r\n", 1)
    response = json.loads(body.decode("utf-8"))
    assert response["id"] == 5
    assert response["result"]["serverInfo"]["name"] == "smda-scheduler"
