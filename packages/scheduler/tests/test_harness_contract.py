import json

import pytest

from helpers import write_minimal_config
from smda_scheduler.config import load_config
from smda_scheduler.context_packets import CodexHarnessContextAdapter, ContextDiscoveryError
from smda_scheduler.role_contracts import CHILD_ROLE_BY_PHASE, PARENT_ROLE_BY_PHASE, ROADMAP_ROLE_BY_PHASE


def setup_contract(tmp_path):
    config_path = tmp_path / 'smda.config.json'
    write_minimal_config(config_path, execution_id='sandcastle', backlog_id='linear', context_id='codex-harness')
    (tmp_path / 'AGENTS.md').write_text('# Boot')
    (tmp_path / 'docs').mkdir()
    config = json.loads(config_path.read_text())
    config['context'].update(skills_dir='skills', harness_contract_path='docs/harness.json')
    config_path.write_text(json.dumps(config))
    roles = {}
    for c in (*CHILD_ROLE_BY_PHASE.values(), *PARENT_ROLE_BY_PHASE.values(), *ROADMAP_ROLE_BY_PHASE.values()):
        role = c.role.value
        phase = 'slice' if role.startswith('graph_') or role == 'roadmap_decomposer' else ('implement' if role in {'child_implementer', 'child_fixer', 'parent_integration_conflict_resolver'} else 'accept')
        roles[role] = {'phase': phase, 'skills': list(c.methodology_skills)}
        for skill in c.methodology_skills:
            p = tmp_path / 'skills' / skill / 'SKILL.md'
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f'# {skill}\nMethodology')
    document = {'schema_version': 2, 'execution_owner': 'smda', 'roles': roles, 'blocking_labels': ['needs-info', 'needs-plan'], 'acceptance': {'child_integration': 'agent', 'parent_merge': 'human', 'merge_target': 'main', 'verification_commands': [['git', 'diff', '--check']], 'human_review_paths': []}}
    (tmp_path / 'docs/harness.json').write_text(json.dumps(document))
    return config_path, document


def packet(tmp_path, config_path):
    return CodexHarnessContextAdapter().build_repo_packet(load_config(config_path, repo_root=tmp_path))


def test_declared_contract_is_validated_and_exposed(tmp_path):
    config, _ = setup_contract(tmp_path)
    result = packet(tmp_path, config)
    assert result.harness_contract_path == tmp_path / 'docs/harness.json'
    assert result.blocking_labels == frozenset({'needs-info', 'needs-plan'})


@pytest.mark.parametrize('mutation', ['unknown_role', 'missing_role', 'wrong_phase', 'wrong_skill', 'wrong_owner', 'unknown_policy', 'empty_labels', 'duplicate_labels', 'wrong_version'])
def test_invalid_contract_fails_closed(tmp_path, mutation):
    config, doc = setup_contract(tmp_path)
    if mutation == 'unknown_role':
        doc['roles']['invented'] = {'phase': 'implement', 'skills': []}
    if mutation == 'missing_role':
        del doc['roles']['child_implementer']
    if mutation == 'wrong_phase':
        doc['roles']['child_implementer']['phase'] = 'accept'
    if mutation == 'wrong_skill':
        doc['roles']['child_implementer']['skills'] = ['to-issues']
    if mutation == 'wrong_owner':
        doc['execution_owner'] = 'interactive'
    if mutation == 'unknown_policy':
        doc['acceptance'] = 'human-only'
    if mutation == 'empty_labels':
        doc['blocking_labels'] = ['']
    if mutation == 'duplicate_labels':
        doc['blocking_labels'] = ['needs-info', 'needs-info']
    if mutation == 'wrong_version':
        doc['schema_version'] = True
    (tmp_path / 'docs/harness.json').write_text(json.dumps(doc))
    with pytest.raises(ContextDiscoveryError):
        packet(tmp_path, config)


def test_contract_requires_methodology_injection(tmp_path):
    config, _ = setup_contract(tmp_path)
    data = json.loads(config.read_text())
    del data['context']['skills_dir']
    config.write_text(json.dumps(data))
    with pytest.raises(ContextDiscoveryError, match='skills_dir'):
        packet(tmp_path, config)


def test_empty_skill_is_rejected(tmp_path):
    config, _ = setup_contract(tmp_path)
    (tmp_path / 'skills/tdd/SKILL.md').write_text('---\nname: tdd\n---\n')
    with pytest.raises(ContextDiscoveryError, match='tdd'):
        packet(tmp_path, config)


def test_contract_path_cannot_escape_repo(tmp_path):
    config, _ = setup_contract(tmp_path)
    data = json.loads(config.read_text())
    data['context']['harness_contract_path'] = '../harness.json'
    config.write_text(json.dumps(data))
    with pytest.raises(ContextDiscoveryError, match='escapes repo root'):
        packet(tmp_path, config)


def test_configured_tick_enforces_project_gate_before_execution(tmp_path):
    from smda_scheduler.backlog import BacklogIssue
    from smda_scheduler.runtime_factory import build_configured_workspace_tick
    from test_runtime_factory import RecordingBacklog, RecordingExecution

    config, _ = setup_contract(tmp_path)
    backlog = RecordingBacklog(BacklogIssue(id='gated', title='Task', state='Todo',
        labels=frozenset({'agent', 'needs-info'}),
        body='Execution: smda-task\nAcceptance criteria: works\nVerification: pytest'))
    execution = RecordingExecution()
    tick = build_configured_workspace_tick(config_path=config, repo_root=tmp_path,
        backlog=backlog, execution=execution, scan_states=['Todo'], scan_label='agent', owner='test')
    result = tick()
    assert execution.requests == []
    assert 'needs-info' in result.detail


@pytest.mark.parametrize('contents', ['{broken', 'null', '[]'])
def test_malformed_contract_is_a_context_error(tmp_path, contents):
    config, _ = setup_contract(tmp_path)
    (tmp_path / 'docs/harness.json').write_text(contents)
    with pytest.raises(ContextDiscoveryError):
        packet(tmp_path, config)


def test_validate_context_reports_rejected_policy(tmp_path):
    from smda_scheduler.cli import run_cli

    config, document = setup_contract(tmp_path)
    document['acceptance'] = 'human-only'
    (tmp_path / 'docs/harness.json').write_text(json.dumps(document))
    result = run_cli(['validate-context', str(config), '--repo-root', str(tmp_path)])
    assert result.exit_code == 1
    assert json.loads(result.stderr)['status'] == 'context_invalid'
    assert 'acceptance requires' in result.stderr


def test_legacy_binding_requires_explicit_acceptance_migration(tmp_path):
    config, document = setup_contract(tmp_path)
    document["schema_version"] = 1
    del document["acceptance"]
    (tmp_path / "docs/harness.json").write_text(json.dumps(document))
    with pytest.raises(ContextDiscoveryError):
        packet(tmp_path, config)
