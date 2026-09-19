import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from test_autonomous_acceptance import git
from test_harness_contract import setup_contract
from test_runtime_factory import RecordingBacklog, _record_graph, _complete_graph_child
from smda_scheduler.backlog import BacklogIssue
from smda_scheduler.config import derive_workspace_paths, load_config
from smda_scheduler.phase_ledger import PhaseLedger
from smda_scheduler.runtime import parent_integration_branch
from smda_scheduler.runtime_factory import build_configured_workspace_tick
from smda_scheduler.scheduling import AttemptOutcome
from smda_scheduler.workflow import RoleResult


class Reviewer:
    def __init__(self):
        self.requests = []

    def run_role_attempt(self, request):
        self.requests.append(request)
        assert request.role == 'parent_qa_reviewer'
        assert git(request.cwd, 'rev-parse', 'HEAD') == request.context_packet['acceptance_snapshot']['candidate']
        return AttemptOutcome(status='succeeded', role_result=RoleResult(verdict='PASS', required_next_action='accept_parent'), raw_result={'report':'Save/Cancel examples passed'})


def prepared_parent(tmp_path, *, merge='agent'):
    config, contract = setup_contract(tmp_path)
    contract.update(schema_version=2, acceptance={
        'child_integration':'agent', 'parent_merge':merge, 'merge_target':'main',
        'verification_commands':[['git','diff','--check']], 'human_review_paths':['secrets/**'],
    })
    (tmp_path/'docs/harness.json').write_text(json.dumps(contract))
    spec=tmp_path/'docs/superpowers/specs/approved.md';spec.parent.mkdir(parents=True)
    spec.write_text('Save commits; Cancel discards. No autosave.')
    (tmp_path/'.gitignore').write_text('.smda/\n')
    git(tmp_path,'init','-b','main');git(tmp_path,'config','user.email','test@example.com');git(tmp_path,'config','user.name','Test')
    git(tmp_path,'add','.');git(tmp_path,'commit','-m','approved project')
    git(tmp_path,'switch','-c',parent_integration_branch('NOTE-1'))
    (tmp_path/'note.txt').write_text('Save and Cancel')
    git(tmp_path,'add','note.txt');git(tmp_path,'commit','-m','feature')
    config_obj=load_config(config,repo_root=tmp_path)
    ledger=PhaseLedger(derive_workspace_paths(config_obj).ledger_path)
    ledger.create_parent_run(parent_id='NOTE-1',initial_phase='PARENT_QA_READY',spec_path='docs/superpowers/specs/approved.md',spec_checksum='sha256:'+hashlib.sha256(spec.read_bytes()).hexdigest(),approval_evidence='user-approved R1')
    _record_graph(ledger,parent_id='NOTE-1',graph_checksum='sha256:graph',children=[_complete_graph_child()])
    backlog=RecordingBacklog(BacklogIssue(id='NOTE-1',title='Edit note',state='In Progress',body='Execution: smda\nSource: docs/superpowers/specs/approved.md',labels=frozenset({'agent'})))
    reviewer=Reviewer()
    tick=build_configured_workspace_tick(config_path=config,repo_root=tmp_path,backlog=backlog,execution=reviewer,scan_states=['In Progress'],scan_label='agent',owner='test')
    return tick, ledger, reviewer, backlog


def test_configured_parent_reviews_verifies_and_lands_exact_commit(tmp_path):
    tick, ledger, reviewer, backlog=prepared_parent(tmp_path)
    original=git(tmp_path,'rev-parse','main');candidate=git(tmp_path,'rev-parse','HEAD')
    assert tick().dispatched == 1
    assert ledger.load_parent_runs()[0]['phase']=='FINAL_ACCEPT_READY'
    attempt=ledger.latest_parent_qa_attempt('NOTE-1')
    assert attempt['result_json']['acceptance_evidence']['checks'][0]['exit_code']==0
    assert git(tmp_path,'rev-parse','main')==original
    assert tick().dispatched == 1
    assert ledger.load_parent_runs()[0]['phase']=='FINAL_ACCEPTED'
    assert git(tmp_path,'rev-parse','main')==candidate
    assert len(reviewer.requests)==1


@pytest.mark.parametrize('change',['candidate','spec','policy','issue','base'])
def test_modified_inputs_after_qa_prevent_delivery(tmp_path,change):
    tick, ledger, reviewer, backlog=prepared_parent(tmp_path)
    tick();original=git(tmp_path,'rev-parse','main')
    if change=='candidate':
        (tmp_path/'note.txt').write_text('autosave');git(tmp_path,'commit','-am','unreviewed')
    elif change=='spec':
        (tmp_path/'docs/superpowers/specs/approved.md').write_text('Autosave approved by nobody')
    elif change=='policy':
        (tmp_path/'docs/harness.json').write_text('{}')
    elif change=='issue':
        backlog.issue=replace(backlog.issue,body=backlog.issue.body+'\nNow add cloud sync')
    elif change=='base':
        git(tmp_path,'switch','-c','other',original)
        (tmp_path/'other.txt').write_text('another parent');git(tmp_path,'add','.');git(tmp_path,'commit','-m','another parent')
        git(tmp_path,'update-ref','refs/heads/main',git(tmp_path,'rev-parse','HEAD'),original)
        original=git(tmp_path,'rev-parse','main')
    result=tick()
    assert result.blocked or result.failed
    assert ledger.load_parent_runs()[0]['phase']!='FINAL_ACCEPTED'
    assert git(tmp_path,'rev-parse','main')==original


def test_human_policy_does_not_auto_accept(tmp_path):
    tick, ledger, reviewer, backlog=prepared_parent(tmp_path,merge='human')
    base=git(tmp_path,'rev-parse','main')
    result=tick()
    assert result.blocked==1
    tick()  # reconcile the durable human-handoff effects
    assert any('human acceptance' in body for _, body in backlog.comments)
    assert git(tmp_path,'rev-parse','main')==base
    assert not reviewer.requests


def test_human_required_tag_blocks_even_under_agent_policy(tmp_path):
    tick, ledger, reviewer, backlog=prepared_parent(tmp_path)
    backlog.issue=replace(backlog.issue,body=backlog.issue.body+'\nMode tags: human_approval_required')
    assert tick().blocked==1
    assert not reviewer.requests


def test_repeated_qa_uses_fresh_revision_branch(tmp_path):
    tick, ledger, reviewer, backlog=prepared_parent(tmp_path)
    original_run=reviewer.run_role_attempt
    def actual_branch_semantics(request):
        # Sandcastle reuses an existing named branch instead of cwd HEAD.
        import subprocess
        exists=subprocess.run(['git','-C',str(request.cwd),'show-ref','--verify','--quiet','refs/heads/'+request.branch]).returncode==0
        git(request.cwd,'switch',*([request.branch] if exists else ['-c',request.branch]))
        return original_run(request)
    reviewer.run_role_attempt=actual_branch_semantics
    tick()
    (tmp_path/'note.txt').write_text('Second reviewed version');git(tmp_path,'commit','-am','revision two')
    ledger.transition_parent(parent_id='NOTE-1',expected_phase='FINAL_ACCEPT_READY',next_phase='PARENT_QA_READY')
    tick()
    assert ledger.load_parent_runs()[0]['phase']=='FINAL_ACCEPT_READY'
    assert len(reviewer.requests)==2
    assert reviewer.requests[0].branch != reviewer.requests[1].branch
    tick()
    assert ledger.load_parent_runs()[0]['phase']=='FINAL_ACCEPTED'


def test_candidate_cannot_change_approved_source_hidden_from_operator_checkout(tmp_path):
    tick, ledger, reviewer, backlog=prepared_parent(tmp_path)
    git(tmp_path,'branch','operator')
    (tmp_path/'docs/superpowers/specs/approved.md').write_text('Scope invented by worker')
    git(tmp_path,'commit','-am','change approved spec')
    git(tmp_path,'switch','operator')
    result=tick()
    assert result.blocked==1
    assert not reviewer.requests


def test_distinct_acceptance_failures_preserve_handoff(tmp_path):
    tick, ledger, reviewer, backlog=prepared_parent(tmp_path,merge='human')
    assert tick().blocked==1
    (tmp_path/'docs/harness.json').write_text('{}')
    result=tick()
    assert result.blocked==1 and result.failed==0
    tick()
    assert any('human acceptance' in body for _,body in backlog.comments)
    assert any('policy changed' in body for _,body in backlog.comments)


def test_failed_host_check_records_failure_and_stops_delivery(tmp_path):
    tick, ledger, reviewer, backlog=prepared_parent(tmp_path)
    contract_path=tmp_path/'docs/harness.json';contract=json.loads(contract_path.read_text())
    contract['acceptance']['verification_commands']=[['git','rev-parse','--verify','nonexistent-ref']]
    contract_path.write_text(json.dumps(contract));git(tmp_path,'commit','-am','explicit failing check')
    config=tmp_path/'smda.config.json'
    tick=build_configured_workspace_tick(config_path=config,repo_root=tmp_path,backlog=backlog,execution=reviewer,scan_states=['In Progress'],scan_label='agent',owner='test')
    base=git(tmp_path,'rev-parse','main')
    assert tick().blocked==1
    assert ledger.latest_parent_qa_attempt('NOTE-1')['status']=='failed'
    assert git(tmp_path,'rev-parse','main')==base


def test_nonblocking_concerns_keep_existing_acceptance_semantics(tmp_path):
    tick, ledger, reviewer, backlog = prepared_parent(tmp_path)
    reviewer.run_role_attempt=lambda request: AttemptOutcome(status='succeeded',role_result=RoleResult(verdict='DONE_WITH_CONCERNS',required_next_action='accept_parent'),raw_result={'report':'Verified; optional cleanup later','concerns':[{'summary':'Optional cleanup','severity':'low'}]})
    assert tick().dispatched == 1
    assert tick().dispatched == 1
    assert ledger.load_parent_runs()[0]['phase']=='FINAL_ACCEPTED'
