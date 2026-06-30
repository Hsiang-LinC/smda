from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO, Literal

from smda_scheduler.cli import CliResult, run_cli


PROTOCOL_VERSION = "2024-11-05"
FrameFormat = Literal["content-length", "json-line"]


def _path_args(arguments: dict[str, Any]) -> list[str]:
    return [str(arguments["config_path"]), "--repo-root", str(arguments["repo_root"])]


def _call_status(arguments: dict[str, Any]) -> CliResult:
    return run_cli(["status", *_path_args(arguments)])


def _call_pause(arguments: dict[str, Any]) -> CliResult:
    return run_cli(
        ["pause", *_path_args(arguments), "--parent", str(arguments["parent"])]
    )


def _call_resume(arguments: dict[str, Any]) -> CliResult:
    return run_cli(
        ["resume", *_path_args(arguments), "--parent", str(arguments["parent"])]
    )


def _call_reconcile_claims(arguments: dict[str, Any]) -> CliResult:
    return run_cli(["reconcile-claims", *_path_args(arguments)])


def _call_force_phase(arguments: dict[str, Any]) -> CliResult:
    target_kind = str(arguments["target_kind"])
    if target_kind not in {"parent", "child"}:
        return CliResult(
            exit_code=1,
            stdout="",
            stderr=json.dumps(
                {
                    "status": "invalid_target_kind",
                    "target_kind": target_kind,
                    "valid_target_kinds": ["parent", "child"],
                }
            ),
        )
    return run_cli(
        [
            "force-phase",
            *_path_args(arguments),
            f"--{target_kind}",
            str(arguments["target_id"]),
            "--to",
            str(arguments["phase"]),
        ]
    )


COMMON_PATH_PROPERTIES = {
    "config_path": {
        "type": "string",
        "description": "Path to smda.config.json or smda.config.yaml.",
    },
    "repo_root": {
        "type": "string",
        "description": "Target repository root for the SMDA workspace.",
    },
}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "smda_status",
        "description": "Read the SMDA local runtime ledger and tracker projection summary.",
        "inputSchema": {
            "type": "object",
            "properties": COMMON_PATH_PROPERTIES,
            "required": ["config_path", "repo_root"],
        },
    },
    {
        "name": "smda_pause",
        "description": "Pause one parent so its children are skipped on dispatch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **COMMON_PATH_PROPERTIES,
                "parent": {"type": "string", "description": "Parent issue id."},
            },
            "required": ["config_path", "repo_root", "parent"],
        },
    },
    {
        "name": "smda_resume",
        "description": "Resume one paused parent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **COMMON_PATH_PROPERTIES,
                "parent": {"type": "string", "description": "Parent issue id."},
            },
            "required": ["config_path", "repo_root", "parent"],
        },
    },
    {
        "name": "smda_reconcile_claims",
        "description": "Release expired child claims from the local scheduler ledger.",
        "inputSchema": {
            "type": "object",
            "properties": COMMON_PATH_PROPERTIES,
            "required": ["config_path", "repo_root"],
        },
    },
    {
        "name": "smda_force_phase",
        "description": "Move an existing parent or child runtime record to a phase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **COMMON_PATH_PROPERTIES,
                "target_kind": {"type": "string", "enum": ["parent", "child"]},
                "target_id": {"type": "string"},
                "phase": {"type": "string"},
            },
            "required": [
                "config_path",
                "repo_root",
                "target_kind",
                "target_id",
                "phase",
            ],
        },
    },
]


TOOL_CALLS = {
    "smda_status": _call_status,
    "smda_pause": _call_pause,
    "smda_resume": _call_resume,
    "smda_reconcile_claims": _call_reconcile_claims,
    "smda_force_phase": _call_force_phase,
}


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if request_id is None:
        return None
    if method == "initialize":
        params = request.get("params", {})
        return _response(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "smda-scheduler", "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return _response(request_id, {"tools": TOOL_DEFINITIONS})
    if method == "tools/call":
        return _handle_tool_call(request_id, request.get("params", {}))
    return _error(request_id, -32601, f"Unknown method: {method}")


def _handle_tool_call(request_id: object, params: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(params.get("name", ""))
    call = TOOL_CALLS.get(tool_name)
    if call is None:
        return _error(request_id, -32602, f"Unknown tool: {tool_name}")
    try:
        result = call(dict(params.get("arguments", {})))
    except KeyError as error:
        return _error(request_id, -32602, f"Missing required argument: {error.args[0]}")
    text = result.stdout if result.exit_code == 0 else result.stderr
    payload: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if result.exit_code != 0:
        payload["isError"] = True
    else:
        try:
            payload["structuredContent"] = json.loads(text)
        except json.JSONDecodeError:
            pass
    return _response(request_id, payload)


def _response(request_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: object, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def run_stdio_server(
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> None:
    input_stream = stdin or sys.stdin.buffer
    output_stream = stdout or sys.stdout.buffer
    while True:
        frame = _read_message(input_stream)
        if frame is None:
            return
        request, frame_format = frame
        response = handle_request(request)
        if response is not None:
            _write_message(output_stream, response, frame_format)


def _read_message(stream: BinaryIO) -> tuple[dict[str, Any], FrameFormat] | None:
    line = stream.readline()
    if line == b"":
        return None
    stripped = line.strip()
    if stripped.startswith(b"{"):
        return json.loads(stripped.decode("utf-8")), "json-line"

    content_length: int | None = None
    while True:
        line = line.rstrip(b"\r\n")
        if line == b"":
            break
        name, _, value = line.partition(b":")
        if name.lower() == b"content-length":
            content_length = int(value.strip())
        line = stream.readline()
        if line == b"":
            return None
    if content_length is None:
        return None
    body = stream.read(content_length)
    if body == b"":
        return None
    return json.loads(body.decode("utf-8")), "content-length"


def _write_message(
    stream: BinaryIO, message: dict[str, Any], frame_format: FrameFormat
) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if frame_format == "json-line":
        stream.write(body + b"\n")
    else:
        stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    stream.flush()
