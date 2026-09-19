import subprocess
from pathlib import Path
import pytest
from smda_scheduler.harness_acceptance import AcceptancePolicy, AcceptanceError, snapshot_candidate, verify_candidate, land_candidate


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def project(tmp_path):
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.email', 'test@example.com')
    git(tmp_path, 'config', 'user.name', 'Test')
    (tmp_path/'note.txt').write_text('base')
    git(tmp_path, 'add', '.'); git(tmp_path, 'commit', '-m', 'base')
    git(tmp_path, 'switch', '-c', 'candidate')
    (tmp_path/'note.txt').write_text('Save and Cancel')
    git(tmp_path, 'commit', '-am', 'feature')
    return AcceptancePolicy.from_dict({'child_integration':'agent', 'parent_merge':'agent', 'merge_target':'main', 'verification_commands':[['git', 'diff', '--check']], 'human_review_paths':['secrets/**']})


def test_verified_candidate_lands_exact_reviewed_revision(tmp_path):
    policy=project(tmp_path)
    snapshot=snapshot_candidate(tmp_path, 'candidate', policy)
    evidence=verify_candidate(tmp_path, snapshot, policy)
    land_candidate(tmp_path, snapshot, evidence, policy)
    assert git(tmp_path, 'rev-parse', 'main') == snapshot['candidate']
    land_candidate(tmp_path, snapshot, evidence, policy) # recovery is idempotent


def test_changed_candidate_or_base_invalidates_evidence(tmp_path):
    policy=project(tmp_path); snap=snapshot_candidate(tmp_path,'candidate',policy)
    evidence=verify_candidate(tmp_path,snap,policy)
    (tmp_path/'note.txt').write_text('unreviewed');git(tmp_path,'commit','-am','later')
    with pytest.raises(AcceptanceError,match='candidate changed'):
        land_candidate(tmp_path,snap,evidence,policy)
    git(tmp_path,'reset','--hard',snap['candidate'])
    git(tmp_path,'update-ref','refs/heads/main',snap['candidate'])
    # An already-landed exact commit is safe recovery.
    land_candidate(tmp_path,snap,evidence,policy)


def test_human_policy_and_protected_files_stop_merge(tmp_path):
    policy=project(tmp_path)
    from dataclasses import replace
    with pytest.raises(AcceptanceError,match='human'):
        snapshot_candidate(tmp_path,'candidate',replace(policy,parent_merge='human'))
    with pytest.raises(AcceptanceError,match='human'):
        snapshot_candidate(tmp_path,'candidate',replace(policy,human_review_paths=('note.txt',)))


def test_failed_verification_cannot_produce_acceptance(tmp_path):
    policy=project(tmp_path)
    from dataclasses import replace
    policy=replace(policy,verification_commands=(('git','rev-parse','--verify','missing'),))
    snapshot=snapshot_candidate(tmp_path,'candidate',policy)
    with pytest.raises(AcceptanceError,match='Verification failed'):
        verify_candidate(tmp_path,snapshot,policy)
    assert git(tmp_path,'rev-parse','main') == snapshot['base']
