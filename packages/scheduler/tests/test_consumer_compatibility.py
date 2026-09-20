from dataclasses import replace
from pathlib import Path
import pytest
from test_harness_contract import setup_contract, packet
from smda_scheduler.runtime import _spec_path
from smda_scheduler.workflow_graph import GraphError


def test_external_installed_skills_are_explicitly_supported(tmp_path):
    import json
    repo=tmp_path/"repo";repo.mkdir()
    config,_=setup_contract(repo)
    external=tmp_path/"plugin";(repo/"skills").rename(external)
    data=json.loads(config.read_text());data["context"]["skills_dir"]=str(external)
    config.write_text(json.dumps(data))
    assert packet(repo,config).skills["tdd"]


def test_configured_feature_source(tmp_path):
    root=tmp_path/"docs/features";root.mkdir(parents=True)
    assert _spec_path("Source: docs/features/slice/spec.md",repo_root=tmp_path,spec_locations=(root,))=="docs/features/slice/spec.md"


@pytest.mark.parametrize("source",["docs/features/../../private.md","../outside.md","/tmp/outside.md"])
def test_source_cannot_escape_configured_roots(tmp_path,source):
    root=tmp_path/"docs/features";root.mkdir(parents=True)
    with pytest.raises(GraphError):
        _spec_path("Source: "+source,repo_root=tmp_path,spec_locations=(root,))


def test_source_symlink_cannot_escape(tmp_path):
    root=tmp_path/"docs/features";root.mkdir(parents=True)
    (root/"escape").symlink_to(tmp_path.parent,target_is_directory=True)
    with pytest.raises(GraphError):
        _spec_path("Source: docs/features/escape/spec.md",repo_root=tmp_path,spec_locations=(root,))


@pytest.mark.parametrize("mode",["smda","smda-roadmap"])
def test_configured_intake_records_feature_source(tmp_path,mode):
    from smda_scheduler.backlog import BacklogIssue
    from smda_scheduler.candidate_routing import classify_candidate
    from smda_scheduler.phase_ledger import PhaseLedger
    from smda_scheduler.runtime import run_parent_candidate_intake,run_roadmap_candidate_intake
    root=tmp_path/"docs/features";root.mkdir(parents=True)
    (root/"approved.md").write_text("---\nstatus: approved\napproved_at: 2026-09-20\napproved_by: human\napproval_evidence: approved case\n---\n# Scope")
    issue=BacklogIssue(id="PA-TEST",title="Scope",state="Todo",body=f"Execution: {mode}\nSource: docs/features/approved.md\nAcceptance criteria: scope\nVerification: pytest")
    ledger=PhaseLedger(tmp_path/"state.sqlite")
    intake=run_parent_candidate_intake if mode=="smda" else run_roadmap_candidate_intake
    intake(issue=issue,decision=classify_candidate(issue,issue_entry_policy="explicit-only"),repo_root=tmp_path,ledger=ledger,spec_locations=(root,))
    assert ledger.load_parent_run("PA-TEST")["spec_path"]=="docs/features/approved.md"


def test_relative_skills_cannot_escape_repo(tmp_path):
    import json
    from smda_scheduler.context_packets import ContextDiscoveryError
    repo=tmp_path/"repo";repo.mkdir()
    config,_=setup_contract(repo)
    external=tmp_path/"plugin";(repo/"skills").rename(external)
    data=json.loads(config.read_text());data["context"]["skills_dir"]="../plugin"
    config.write_text(json.dumps(data))
    with pytest.raises(ContextDiscoveryError,match="escapes"):
        packet(repo,config)


def test_skill_file_cannot_escape_selected_root(tmp_path):
    from smda_scheduler.skill_loader import load_skill_methodology,SkillNotFoundError
    root=tmp_path/"skills";(root/"tdd").mkdir(parents=True)
    external=tmp_path/"outside.md";external.write_text("Unselected skill")
    (root/"tdd/SKILL.md").symlink_to(external)
    with pytest.raises(SkillNotFoundError):
        load_skill_methodology(root,"tdd")


def test_unrelated_invalid_source_does_not_block_roadmap_snapshot(tmp_path):
    from smda_scheduler.backlog import BacklogIssue,BacklogPage
    from smda_scheduler.runtime import _open_parent_snapshot
    class Backlog:
        def list_issues(self,**kwargs):
            return BacklogPage(issues=(BacklogIssue(id="OLD",title="Old",state="Todo",body="Execution: smda\nSource: docs/legacy/spec.md"),)) if kwargs["state"]=="Todo" else BacklogPage(issues=())
    result=_open_parent_snapshot(Backlog(),exclude_id="CURRENT",repo_root=tmp_path,spec_locations=(tmp_path/"docs/features",))
    assert len(result)==1 and result[0]["source"]==""
