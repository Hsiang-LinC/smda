from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from smda_scheduler.adapters import AdapterDescriptor
from smda_scheduler.backlog import BacklogError, BacklogIssue, BacklogPage


@dataclass(frozen=True)
class _LedgerSection:
    path: Path
    issue_id: str
    start: int
    end: int
    lines: list[str]
    archive_state: str | None = None


class LocalLedgerBacklogAdapter:
    def __init__(
        self,
        *,
        root: Path,
        active_path: str = "docs/work-ledger/active.md",
        completed_path: str = "docs/work-ledger/completed.md",
        abandoned_path: str = "docs/work-ledger/abandoned.md",
    ) -> None:
        self._root = root
        self._active_path = self._resolve(active_path)
        self._completed_path = self._resolve(completed_path)
        self._abandoned_path = self._resolve(abandoned_path)

    def descriptor(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            id="local-ledger",
            version="0.1.0",
            capabilities=frozenset(
                {
                    "create_child",
                    "coarse_states",
                    "comments",
                    "hierarchy",
                    "blocking_relations",
                }
            ),
        )

    def fetch_issue(self, issue_id: str) -> BacklogIssue:
        return self._issue_from_section(self._find_section(issue_id))

    def list_issues(
        self,
        *,
        state: str,
        label: str,
        parent_id: str | None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> BacklogPage:
        del cursor
        issues = []
        for section in self._all_sections():
            issue = self._issue_from_section(section)
            if issue.state != state:
                continue
            if parent_id is not None and issue.parent_id != parent_id:
                continue
            if label and issue.labels and label not in issue.labels:
                continue
            issues.append(issue)
        return BacklogPage(
            issues=tuple(sorted(issues, key=lambda issue: issue.id)[:limit])
        )

    def set_coarse_state(self, issue_id: str, state: str) -> None:
        section = self._find_section(issue_id, writable=True)
        status = _STATE_TO_STATUS.get(state, state.lower().replace(" ", "-"))
        self._replace_or_append_field(section, "status", status)

    def comment(self, issue_id: str, body: str) -> None:
        section = self._find_section(issue_id, writable=True)
        self._append_field(section, "smda-comment", body)

    def create_child(
        self,
        *,
        parent_id: str,
        title: str,
        body: str,
        labels: set[str] | frozenset[str] | None = None,
    ) -> BacklogIssue:
        self.fetch_issue(parent_id)
        child_id = self._next_child_id(parent_id)
        fields = {
            "status": "planned",
            "title": title,
            "execution": _body_field(body, "Execution") or "smda-child",
            "parent": parent_id,
            "node-id": _body_field(body, "Node id") or child_id,
            "graph-checksum": _body_field(body, "Graph checksum") or "",
            "blocked-by": "none",
            "acceptance": _body_field(body, "Acceptance criteria") or "",
            "verify": _body_field(body, "Verification") or "",
            "next": "dispatch through SMDA",
            "updated": date.today().isoformat(),
        }
        if labels:
            fields["labels"] = ", ".join(sorted(labels))

        self._active_path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_lines(self._active_path)
        if not existing:
            existing = ["# Active Work"]
        if existing and existing[-1].strip():
            existing.append("")
        existing.extend(
            [
                "",
                f"## {child_id}",
                *[f"- {key}: {value}" for key, value in fields.items()],
            ]
        )
        self._write_lines(self._active_path, existing)
        return self.fetch_issue(child_id)

    def project_hierarchy(self, parent_id: str) -> list[str]:
        self.fetch_issue(parent_id)
        return sorted(
            issue.id
            for issue in (
                self._issue_from_section(section) for section in self._all_sections()
            )
            if issue.parent_id == parent_id
        )

    def link_blocking(self, *, blocker_id: str, blocked_id: str) -> None:
        self.fetch_issue(blocker_id)
        section = self._find_section(blocked_id, writable=True)
        fields = _fields(section.lines)
        blockers = _split_csv(fields.get("blocked-by", ""))
        merged = sorted({*blockers, blocker_id} - {"none"})
        self._replace_or_append_field(
            section,
            "blocked-by",
            ", ".join(merged) or "none",
        )

    def query_blocked_by(self, issue_id: str) -> list[str]:
        section = self._find_section(issue_id)
        return sorted(
            set(_split_csv(_fields(section.lines).get("blocked-by", ""))) - {"none"}
        )

    def _resolve(self, raw_path: str) -> Path:
        path = Path(raw_path)
        return path if path.is_absolute() else self._root / path

    def _find_section(self, issue_id: str, *, writable: bool = False) -> _LedgerSection:
        paths = (self._active_path,) if writable else (
            self._active_path,
            self._completed_path,
            self._abandoned_path,
        )
        for section in self._sections_for_paths(paths):
            if section.issue_id == issue_id:
                return section
        raise BacklogError(f"Local ledger issue not found: {issue_id}")

    def _all_sections(self) -> list[_LedgerSection]:
        return self._sections_for_paths(
            (self._active_path, self._completed_path, self._abandoned_path)
        )

    def _sections_for_paths(self, paths: tuple[Path, ...]) -> list[_LedgerSection]:
        sections: list[_LedgerSection] = []
        for path in paths:
            lines = self._read_lines(path)
            starts = [
                (index, match.group(1).strip())
                for index, line in enumerate(lines)
                if (match := re.match(r"^##\s+(.+?)\s*$", line))
            ]
            archive_state = None
            if path == self._completed_path:
                archive_state = "Done"
            elif path == self._abandoned_path:
                archive_state = "Canceled"
            for offset, (start, issue_id) in enumerate(starts):
                end = starts[offset + 1][0] if offset + 1 < len(starts) else len(lines)
                sections.append(
                    _LedgerSection(
                        path=path,
                        issue_id=issue_id,
                        start=start,
                        end=end,
                        lines=lines[start + 1 : end],
                        archive_state=archive_state,
                    )
                )
        return sections

    def _issue_from_section(self, section: _LedgerSection) -> BacklogIssue:
        fields = _fields(section.lines)
        status = fields.get("status", "")
        state = section.archive_state or _STATUS_TO_STATE.get(status, status)
        title = fields.get("title") or section.issue_id
        labels = frozenset(_split_csv(fields.get("labels", "")))
        parent_id = fields.get("parent") or None
        comments = _field_values(section.lines, "smda-comment")
        return BacklogIssue(
            id=section.issue_id,
            title=title,
            state=state,
            body=_normalized_body(section.lines, fields),
            parent_id=parent_id,
            labels=labels,
            comments=comments,
        )

    def _replace_or_append_field(
        self,
        section: _LedgerSection,
        key: str,
        value: str,
    ) -> None:
        lines = self._read_lines(section.path)
        pattern = re.compile(rf"^-\s+{re.escape(key)}\s*:", re.I)
        for index in range(section.start + 1, section.end):
            if pattern.match(lines[index]):
                lines[index] = f"- {key}: {value}"
                self._write_lines(section.path, lines)
                return
        lines.insert(section.start + 1, f"- {key}: {value}")
        self._write_lines(section.path, lines)

    def _append_field(self, section: _LedgerSection, key: str, value: str) -> None:
        lines = self._read_lines(section.path)
        lines[section.end:section.end] = _field_lines(key, value)
        self._write_lines(section.path, lines)

    def _next_child_id(self, parent_id: str) -> str:
        used = {section.issue_id for section in self._all_sections()}
        number = 1
        while f"{parent_id}-C{number}" in used:
            number += 1
        return f"{parent_id}-C{number}"

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    @staticmethod
    def _write_lines(path: Path, lines: list[str]) -> None:
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_local_ledger_backlog_adapter(
    *,
    repo_root: Path,
    active_path: str = "docs/work-ledger/active.md",
    completed_path: str = "docs/work-ledger/completed.md",
    abandoned_path: str = "docs/work-ledger/abandoned.md",
) -> LocalLedgerBacklogAdapter:
    return LocalLedgerBacklogAdapter(
        root=repo_root,
        active_path=active_path,
        completed_path=completed_path,
        abandoned_path=abandoned_path,
    )


_STATUS_TO_STATE = {
    "planned": "Todo",
    "in-progress": "In Progress",
    "active": "In Progress",
    "blocked": "Blocked",
    "done": "Done",
    "abandoned": "Canceled",
}

_STATE_TO_STATUS = {
    "Todo": "planned",
    "In Progress": "in-progress",
    "Blocked": "blocked",
    "Human Review": "blocked",
    "Done": "done",
    "Canceled": "abandoned",
}


def _fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^-\s+([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$", line)
        if match:
            fields[match.group(1).lower()] = _field_value_with_continuation(
                lines,
                index,
                match.group(2),
            )
        index += 1
    return fields


def _field_values(lines: list[str], key: str) -> list[str]:
    pattern = re.compile(rf"^-\s+{re.escape(key)}\s*:\s*(.*?)\s*$", re.I)
    values = []
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            values.append(_field_value_with_continuation(lines, index, match.group(1)))
    return values


def _field_value_with_continuation(
    lines: list[str],
    index: int,
    first_line: str,
) -> str:
    value = [first_line]
    cursor = index + 1
    while cursor < len(lines):
        line = lines[cursor]
        if not line.startswith(" ") or line.lstrip().startswith("- "):
            break
        value.append(line.strip())
        cursor += 1
    return "\n".join(value)


def _field_lines(key: str, value: str) -> list[str]:
    lines = value.splitlines() or [""]
    return [f"- {key}: {lines[0]}", *[f"  {line}" for line in lines[1:]]]


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalized_body(lines: list[str], fields: dict[str, str]) -> str:
    header_lines = []
    if execution := fields.get("execution"):
        header_lines.append(f"Execution: {execution}")
    if parent := fields.get("parent"):
        header_lines.append(f"Parent issue: {parent}")
    if node_id := fields.get("node-id"):
        header_lines.append(f"Node id: {node_id}")
    if graph_checksum := fields.get("graph-checksum"):
        header_lines.append(f"Graph checksum: {graph_checksum}")
    if acceptance := fields.get("acceptance"):
        header_lines.append(f"Acceptance criteria: {acceptance}")
    if verify := fields.get("verify"):
        header_lines.append(f"Verification: {verify}")

    raw = "\n".join(line for line in lines if line.strip()).strip()
    return "\n\n".join(part for part in ("\n".join(header_lines), raw) if part)


def _body_field(body: str, label: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", re.I | re.M)
    match = pattern.search(body)
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None
