from dataclasses import replace

from test_acceptance_runtime import prepared_parent
from test_autonomous_acceptance import git
from smda_scheduler.scheduling import ChildRunState, SchedulerState
from smda_scheduler.workflow import ChildPhase


def prepared_task(tmp_path):
    tick,ledger,reviewer,backlog=prepared_parent(tmp_path)
    backlog.issue=replace(backlog.issue,id='TASK-1',title='Edit note',body='Execution: smda-task\nSource: user-request TASK-1\nAcceptance criteria: Save and Cancel\nVerification: git diff --check')
    git(tmp_path,'branch','task-candidate','HEAD')
    ledger.save_scheduler_state(SchedulerState(children={'TASK-1':ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}))
    ledger.record_attempt_request(attempt_id='TASK-1-QUALITY_REVIEWING-1',child_id='TASK-1',phase=ChildPhase.QUALITY_REVIEWING,idempotency_key='quality-1',request_json={})
    ledger.record_attempt_result(attempt_id='TASK-1-QUALITY_REVIEWING-1',status='succeeded',result_json={'verdict':'PASS','required_next_action':'accept_candidate','branch':'task-candidate'},error_message=None)
    return tick,ledger,reviewer,backlog


def test_checked_task_qa_precedes_main_delivery(tmp_path):
    tick,ledger,reviewer,backlog=prepared_task(tmp_path)
    base=git(tmp_path,'rev-parse','main');candidate=git(tmp_path,'rev-parse','task-candidate')
    assert tick().dispatched==1
    assert len(reviewer.requests)==1
    assert git(tmp_path,'rev-parse','main')==base
    assert tick().dispatched==1
    assert git(tmp_path,'rev-parse','main')==candidate
    tick() # reconcile tracker effects; no duplicate review
    assert len(reviewer.requests)==1
    assert ('TASK-1','Done') in backlog.states


def test_checked_task_continues_after_quality_review_under_normal_scan_states(tmp_path):
    from smda_scheduler.backlog import BacklogPage
    from smda_scheduler.scheduling import AttemptOutcome
    from smda_scheduler.workflow import RoleResult
    tick,ledger,reviewer,backlog=prepared_task(tmp_path)
    ledger.save_scheduler_state(SchedulerState(children={}))
    backlog.list_issues=lambda **kw: BacklogPage(issues=(backlog.issue,) if backlog.issue.state==kw['state'] else ())
    original_set=backlog.set_coarse_state
    def set_state(issue_id,state):
        original_set(issue_id,state)
        backlog.issue=replace(backlog.issue,state=state)
    backlog.set_coarse_state=set_state
    original_review=reviewer.run_role_attempt
    def execute(request):
        if request.role=='parent_qa_reviewer': return original_review(request)
        verdict,action=('DONE','submit_for_spec_review') if request.role=='child_implementer' else ('PASS','accept_candidate')
        return AttemptOutcome(status='succeeded',role_result=RoleResult(verdict=verdict,required_next_action=action),branch='task-candidate')
    reviewer.run_role_attempt=execute
    for _ in range(7): tick()
    assert backlog.issue.state=='Done'
    assert git(tmp_path,'rev-parse','main')==git(tmp_path,'rev-parse','task-candidate')


def prepared_roadmap(tmp_path, *, separate_source=False):
    tick,ledger,reviewer,backlog=prepared_parent(tmp_path)
    parent=ledger.load_parent_run('NOTE-1')
    if separate_source:
        import hashlib
        source="docs/superpowers/specs/roadmap.md"
        text="Roadmap: notes"
        (tmp_path/source).write_text(text)
        git(tmp_path,"add",".")
        git(tmp_path,"commit","-m","Approved roadmap")
        parent={**parent,"spec_path":source,"spec_checksum":"sha256:"+hashlib.sha256(text.encode()).hexdigest()}
    ledger.create_parent_run(parent_id='ROAD-1',initial_phase='ROADMAP_PUBLISHED',spec_path=parent['spec_path'],spec_checksum=parent['spec_checksum'],approval_evidence='approved roadmap R1')
    ledger.record_roadmap_members('ROAD-1',[{'node_id':'notes','title':'Edit notes','body':'Save and Cancel','risk_level':'low','dependencies':[]}])
    ledger.record_roadmap_member_projection(roadmap_id='ROAD-1',node_id='notes',issue_id='NOTE-1')
    return tick,ledger,reviewer,backlog


def test_roadmap_member_and_aggregate_share_checked_delivery(tmp_path):
    tick,ledger,reviewer,backlog=prepared_roadmap(tmp_path)
    base=git(tmp_path,'rev-parse','main')
    assert tick().dispatched==1
    assert reviewer.requests[-1].context_packet['acceptance_snapshot']['target']=='smda/ROAD-1/integration'
    assert tick().dispatched==1
    assert ledger.load_parent_run('NOTE-1')['phase']=='FINAL_ACCEPTED'
    assert git(tmp_path,'rev-parse','main')==base
    backlog.issue=replace(backlog.issue,id='ROAD-1',title='Notes roadmap',body='Execution: smda-roadmap\nSource: docs/superpowers/specs/approved.md')
    assert tick().dispatched==1
    assert len(reviewer.requests)==2
    assert git(tmp_path,'rev-parse','main')==base
    assert tick().dispatched==1
    assert ledger.load_parent_run('ROAD-1')['phase']=='ROADMAP_COMPLETED'
    assert git(tmp_path,'rev-parse','main')==git(tmp_path,'rev-parse','smda/ROAD-1/integration')

def test_task_rejection_preserves_findings(tmp_path):
    from smda_scheduler.scheduling import AttemptOutcome
    from smda_scheduler.workflow import RoleResult
    tick,ledger,reviewer,backlog=prepared_task(tmp_path)
    reviewer.run_role_attempt=lambda request: AttemptOutcome(status="succeeded", role_result=RoleResult(verdict="FAIL", required_next_action="escalate"), raw_result={"report":"Save loses edits"})
    base=git(tmp_path,"rev-parse","main")
    tick()
    attempt=ledger.latest_parent_qa_attempt("TASK-1")
    assert attempt["result_json"]["report"]=="Save loses edits"
    assert git(tmp_path,"rev-parse","main")==base


def test_completed_task_reconciliation_does_not_reland(tmp_path):
    tick,ledger,reviewer,backlog=prepared_task(tmp_path)
    tick();tick()
    git(tmp_path,"checkout","main")
    git(tmp_path,"commit","--allow-empty","-m","Later authorized delivery")
    newer=git(tmp_path,"rev-parse","main")
    git(tmp_path,"checkout","task-candidate")
    tick()
    assert git(tmp_path,"rev-parse","main")==newer
    assert all(op["status"]=="completed" for op in ledger.load_parent_land_operations())
    assert not any(state=="Human Review" for _,state in backlog.states)


def test_task_stale_body_blocks_delivery(tmp_path):
    tick,ledger,reviewer,backlog=prepared_task(tmp_path)
    base=git(tmp_path,"rev-parse","main")
    tick()
    backlog.issue=replace(backlog.issue,body=backlog.issue.body+"\nAlso autosave")
    tick();tick()
    assert git(tmp_path,"rev-parse","main")==base
    assert ("TASK-1","Human Review") in backlog.states


def test_roadmap_rejects_member_source_changed_in_aggregate(tmp_path):
    tick,ledger,reviewer,backlog=prepared_roadmap(tmp_path, separate_source=True)
    tick();tick()
    base=git(tmp_path,"rev-parse","main")
    git(tmp_path,"checkout","smda/ROAD-1/integration")
    (tmp_path/"docs/superpowers/specs/approved.md").write_text("Silently changed scope")
    git(tmp_path,"add",".")
    git(tmp_path,"commit","-m","Changed member source")
    git(tmp_path,"checkout","smda/note-1/integration")
    backlog.issue=replace(backlog.issue,id="ROAD-1",title="Roadmap",body="Execution: smda-roadmap\nSource: docs/superpowers/specs/roadmap.md")
    tick();tick()
    assert len(reviewer.requests)==1
    assert git(tmp_path,"rev-parse","main")==base
    assert ("ROAD-1","Human Review") in backlog.states


def test_checked_task_missing_source_stops_before_execution(tmp_path):
    tick,ledger,reviewer,backlog=prepared_task(tmp_path)
    backlog.issue=replace(backlog.issue,body="Execution: smda-task\nAcceptance criteria: Save\nVerification: git diff --check")
    base=git(tmp_path,"rev-parse","main")
    tick();tick()
    assert not reviewer.requests
    assert git(tmp_path,"rev-parse","main")==base
    assert ("TASK-1","Human Review") in backlog.states


def test_checked_task_human_policy_stops_before_delivery_qa(tmp_path):
    tick,ledger,reviewer,backlog=prepared_parent(tmp_path,merge="human")
    backlog.issue=replace(backlog.issue,id="TASK-1",body="Execution: smda-task\nSource: user-request TASK-1\nAcceptance criteria: Save\nVerification: git diff --check")
    git(tmp_path,"branch","task-candidate","HEAD")
    ledger.save_scheduler_state(SchedulerState(children={"TASK-1":ChildRunState(phase=ChildPhase.QUALITY_REVIEW_PASSED)}))
    ledger.record_attempt_request(attempt_id="task-quality",child_id="TASK-1",phase=ChildPhase.QUALITY_REVIEWING,idempotency_key="task-quality",request_json={})
    ledger.record_attempt_result(attempt_id="task-quality",status="succeeded",result_json={"verdict":"PASS","required_next_action":"accept_candidate","branch":"task-candidate"},error_message=None)
    base=git(tmp_path,"rev-parse","main")
    tick();tick()
    assert not reviewer.requests
    assert git(tmp_path,"rev-parse","main")==base
    assert ("TASK-1","Human Review") in backlog.states
