from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from smda_scheduler.workflow import ChildPhase, GraphError, ParentPhase, RoadmapPhase


class RoleName(StrEnum):
    GRAPH_DECOMPOSER = "graph_decomposer"
    GRAPH_FIXER = "graph_fixer"
    ROADMAP_DECOMPOSER = "roadmap_decomposer"
    GRAPH_SPEC_REVIEWER = "graph_spec_reviewer"
    GRAPH_EXECUTION_REVIEWER = "graph_execution_reviewer"
    PARENT_QA_REVIEWER = "parent_qa_reviewer"
    CHILD_IMPLEMENTER = "child_implementer"
    CHILD_SPEC_REVIEWER = "child_spec_reviewer"
    CHILD_FIXER = "child_fixer"
    CHILD_QUALITY_REVIEWER = "child_quality_reviewer"


@dataclass(frozen=True)
class RoleContract:
    role: RoleName
    schema_id: str
    output_tag: str
    prompt_template: str
    # Methodology skills (ADR-0004) injected into the prompt by the runner.
    methodology_skills: tuple[str, ...] = ()

    def render_prompt(self, values: dict[str, str]) -> str:
        prompt = self.prompt_template.format(**values)
        return (
            f"{prompt}\n\n"
            "Structured output contract:\n"
            f"Emit exactly one <{self.output_tag}>...</{self.output_tag}> block "
            f"containing the JSON object for schema {self.schema_id}."
        )


PARENT_ROLE_BY_PHASE: dict[ParentPhase, RoleContract] = {
    ParentPhase.GRAPH_DECOMPOSING: RoleContract(
        role=RoleName.GRAPH_DECOMPOSER,
        methodology_skills=("to-issues",),
        schema_id="smda.graph-decomposer-result.v1",
        output_tag="smda_graph_decomposer_result",
        prompt_template="""Role: graph decomposer
Phase: {phase}
Parent issue: {parent_issue_id} - {parent_title}

Decompose the approved parent spec into a dependency-aware child graph. Keep
each child scoped to an independently reviewable implementation slice.
Do not publish child issues or mutate tracker state; the SMDA Scheduler owns
graph review, publication, and lifecycle writes.

Parent issue body:
{parent_body}

Approved spec path: {spec_path}
Spec checksum: {spec_checksum}
Approval evidence: {approval_evidence}

Approved spec:
{spec_text}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    ),
    ParentPhase.GRAPH_FIXING: RoleContract(
        role=RoleName.GRAPH_FIXER,
        methodology_skills=("diagnose",),
        schema_id="smda.graph-decomposer-result.v1",
        output_tag="smda_graph_fixer_result",
        prompt_template="""Role: graph fixer
Phase: {phase}
Parent issue: {parent_issue_id} - {parent_title}

A graph review failed. Revise the current child graph to resolve only the
findings below; change only findings-scoped nodes and edges. If the findings
require a broader rewrite, report it for human review instead of guessing. Do
not publish child issues or mutate tracker state.

Review findings:
{review_findings}

Current graph checksum: {graph_checksum}
Current children:
{children}
Current dependency edges:
{dependency_edges}

Parent issue body:
{parent_body}

Approved spec path: {spec_path}
Spec checksum: {spec_checksum}
Approval evidence: {approval_evidence}

Approved spec:
{spec_text}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return the full revised graph as one structured result object for schema
{schema_id}, using verdict DONE with required_next_action
submit_for_graph_review.""",
    ),
    ParentPhase.GRAPH_SPEC_REVIEWING: RoleContract(
        role=RoleName.GRAPH_SPEC_REVIEWER,
        methodology_skills=("grill-with-docs",),
        schema_id="smda.review-result.v1",
        output_tag="smda_graph_spec_review_result",
        prompt_template="""Role: graph spec reviewer
Phase: {phase}
Parent issue: {parent_issue_id} - {parent_title}

Review the child graph against the approved parent spec. Check that every child
is necessary, scoped, independently reviewable, and dependency-ordered.
Do not publish child issues or mutate tracker state; the SMDA Scheduler owns
graph publication and lifecycle writes.
Use verdict PASS with required_next_action submit_for_graph_execution_review
when the graph matches the spec; FAIL to send the graph back for a fix;
DONE_WITH_CONCERNS with submit_for_graph_execution_review for minor,
non-blocking issues recorded in report.

Parent issue body:
{parent_body}

Approved spec path: {spec_path}
Spec checksum: {spec_checksum}
Approval evidence: {approval_evidence}

Approved spec:
{spec_text}

Graph checksum: {graph_checksum}
Child graph:
{children}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    ),
    ParentPhase.GRAPH_EXECUTION_REVIEWING: RoleContract(
        role=RoleName.GRAPH_EXECUTION_REVIEWER,
        methodology_skills=("grill-with-docs",),
        schema_id="smda.review-result.v1",
        output_tag="smda_graph_execution_review_result",
        prompt_template="""Role: graph execution reviewer
Phase: {phase}
Parent issue: {parent_issue_id} - {parent_title}

Review dependency order, merge risk, and safe parallelism before child issue
publication. Check that independent children can run concurrently and dependent
children have explicit dependency edges.
Do not publish child issues or mutate tracker state; the SMDA Scheduler owns
graph publication and lifecycle writes.
Use verdict PASS with required_next_action publish_child_issues when the graph
is safe to publish; FAIL to send it back for a fix; DONE_WITH_CONCERNS with
publish_child_issues for minor, non-blocking issues recorded in report.

Parent issue body:
{parent_body}

Approved spec path: {spec_path}
Spec checksum: {spec_checksum}
Approval evidence: {approval_evidence}

Approved spec:
{spec_text}

Graph checksum: {graph_checksum}
Child graph:
{children}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    ),
    ParentPhase.PARENT_QA_REVIEWING: RoleContract(
        role=RoleName.PARENT_QA_REVIEWER,
        methodology_skills=("triage",),
        schema_id="smda.review-result.v1",
        output_tag="smda_parent_qa_review_result",
        prompt_template="""Role: parent QA reviewer
Phase: {phase}
Parent issue: {parent_issue_id} - {parent_title}

Review the final parent integration branch against the approved parent spec,
child graph, and repo quality gates. Confirm the integrated feature is coherent
as one parent-level change, not just a collection of individually accepted
children. Do not mutate tracker state; the SMDA Scheduler owns final accept,
remediation routing, and lifecycle writes.
Use verdict PASS with required_next_action accept_parent when the parent is
ready for final accept. Use verdict FAIL with required_next_action
plan_remediation when the integrated change needs a bounded remediation child.
Use verdict DONE_WITH_CONCERNS with required_next_action accept_parent for
minor, non-blocking issues not worth remediation; put the concern in report.

Parent issue body:
{parent_body}

Approved spec path: {spec_path}
Spec checksum: {spec_checksum}
Approval evidence: {approval_evidence}

Approved spec:
{spec_text}

Graph checksum: {graph_checksum}
Child graph:
{children}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    ),
}


CHILD_ROLE_BY_PHASE: dict[ChildPhase, RoleContract] = {
    ChildPhase.IMPLEMENTING: RoleContract(
        role=RoleName.CHILD_IMPLEMENTER,
        methodology_skills=("tdd",),
        schema_id="smda.child-implementer-result.v1",
        output_tag="smda_child_implementer_result",
        prompt_template="""Role: child implementer
Phase: {phase}
Parent issue: {parent_issue_id}
Child: {child_id} - {child_title}

Implement the child task in an isolated worktree. Keep the change scoped to the
child issue and its acceptance criteria. Do not call backlog tools or mutate
tracker state; the SMDA Scheduler owns lifecycle writes.

Return the child implementation payload only, not a scheduler report envelope.
Use verdict DONE with required_next_action submit_for_spec_review when the patch
is ready for SMDA review. Use verdict BLOCKED with required_next_action
request_human_review when the child cannot proceed because of missing context or
environment. Put changed files, verification evidence, and residual risks in
the report string.

Child body:
{child_body}

Acceptance criteria:
{acceptance_criteria}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    ),
    ChildPhase.SPEC_REVIEWING: RoleContract(
        role=RoleName.CHILD_SPEC_REVIEWER,
        methodology_skills=("grill-with-docs",),
        schema_id="smda.review-result.v1",
        output_tag="smda_child_spec_review_result",
        prompt_template="""Role: child spec reviewer
Phase: {phase}
Parent issue: {parent_issue_id}
Child: {child_id} - {child_title}

Review the candidate only against the parent spec, child issue, and acceptance
criteria. Prefer concrete findings over broad rewrites. Do not apply fixes;
return a structured review result for the scheduler to route.
Use verdict PASS with required_next_action submit_for_quality_review when the
candidate satisfies the spec. Use verdict FAIL with required_next_action
fix_spec when it needs scoped fixes. Use verdict DONE_WITH_CONCERNS with
required_next_action submit_for_quality_review for minor, non-blocking issues
not worth a fix loop; put the concern in report so it travels downstream.

Child body:
{child_body}

Acceptance criteria:
{acceptance_criteria}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    ),
    ChildPhase.FIXING_SPEC: RoleContract(
        role=RoleName.CHILD_FIXER,
        methodology_skills=("diagnose",),
        schema_id="smda.child-fixer-result.v1",
        output_tag="smda_child_fixer_result",
        prompt_template="""Role: child fixer
Phase: {phase}
Parent issue: {parent_issue_id}
Child: {child_id} - {child_title}

Fix the prior review findings while preserving the child issue boundary. Do not
expand scope or mutate tracker state. If the issue boundary is wrong, report the
conflict instead of applying unrelated changes.
Use verdict DONE with required_next_action submit_for_spec_review when the fix
is ready for another spec review.

Child body:
{child_body}

Acceptance criteria:
{acceptance_criteria}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    ),
    ChildPhase.FIXING_QUALITY: RoleContract(
        role=RoleName.CHILD_FIXER,
        methodology_skills=("diagnose",),
        schema_id="smda.child-fixer-result.v1",
        output_tag="smda_child_fixer_result",
        prompt_template="""Role: child fixer
Phase: {phase}
Parent issue: {parent_issue_id}
Child: {child_id} - {child_title}

Fix the prior quality review findings while preserving the child issue boundary.
Do not expand scope or mutate tracker state. If the issue boundary is wrong,
report the conflict instead of applying unrelated changes.
Use verdict DONE with required_next_action submit_for_quality_review when the
fix is ready for another quality review.

Child body:
{child_body}

Acceptance criteria:
{acceptance_criteria}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    ),
    ChildPhase.QUALITY_REVIEWING: RoleContract(
        role=RoleName.CHILD_QUALITY_REVIEWER,
        methodology_skills=("improve-codebase-architecture",),
        schema_id="smda.review-result.v1",
        output_tag="smda_child_quality_review_result",
        prompt_template="""Role: child quality reviewer
Phase: {phase}
Parent issue: {parent_issue_id}
Child: {child_id} - {child_title}

Review implementation quality, regression risk, and verification evidence.
Accept only when the candidate is ready for deterministic parent-branch
integration. Do not apply fixes or mutate tracker state.
Use verdict PASS with required_next_action accept_candidate when the candidate
is ready for parent integration. Use verdict DONE_WITH_CONCERNS with
required_next_action accept_candidate for minor, non-blocking issues not worth a
fix loop; put the concern in report so it travels downstream.

Child body:
{child_body}

Acceptance criteria:
{acceptance_criteria}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    ),
}


ROADMAP_ROLE_BY_PHASE: dict[RoadmapPhase, RoleContract] = {
    RoadmapPhase.ROADMAP_DECOMPOSING: RoleContract(
        role=RoleName.ROADMAP_DECOMPOSER,
        methodology_skills=("to-prd", "to-issues"),
        schema_id="smda.roadmap-decomposer-result.v1",
        output_tag="smda_roadmap_decomposer_result",
        prompt_template="""Role: roadmap decomposer
Phase: {phase}
Roadmap issue: {roadmap_issue_id} - {roadmap_title}

Author the complete member parent set from the approved Roadmap Spec. Each
member parent must be independently executable as `Execution: smda`, and the
roadmap_edges must express parent-to-parent dispatch dependencies.

Use the read-only open-parent snapshot to avoid duplicate scope and to author
cross-roadmap edges where this roadmap depends on existing open parents. You
MUST NOT create issues or mutate tracker state; the SMDA Scheduler owns
publication, ledger writes, blocking links, and lifecycle updates.

Roadmap issue body:
{roadmap_body}

Approved roadmap spec path: {spec_path}
Spec checksum: {spec_checksum}
Approval evidence: {approval_evidence}

Approved roadmap spec:
{spec_text}

Read-only open-parent snapshot:
{open_parent_snapshot}

Repo bootloader:
{bootloader_text}

Spec locations:
{spec_locations}

ADR locations:
{adr_locations}

Quality gates:
{quality_gates}

Return one structured result object for schema {schema_id}.""",
    )
}


def roadmap_role_contract_for_phase(phase: RoadmapPhase) -> RoleContract:
    try:
        return ROADMAP_ROLE_BY_PHASE[phase]
    except KeyError as error:
        raise GraphError(f"No roadmap role contract mapped for phase: {phase}") from error


def parent_role_contract_for_phase(phase: ParentPhase) -> RoleContract:
    try:
        return PARENT_ROLE_BY_PHASE[phase]
    except KeyError as error:
        raise GraphError(f"No parent role contract mapped for phase: {phase}") from error


def child_role_contract_for_phase(phase: ChildPhase) -> RoleContract:
    try:
        return CHILD_ROLE_BY_PHASE[phase]
    except KeyError as error:
        raise GraphError(f"No child role contract mapped for phase: {phase}") from error
