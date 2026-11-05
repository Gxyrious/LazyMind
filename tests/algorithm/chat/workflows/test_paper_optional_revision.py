"""Optional workflow revision publishes a valid manuscript even when a candidate is rejected."""
import copy
import json
from concurrent.futures import CancelledError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import lazyllm
import pytest

from lazymind.chat.engine.subagent.context import SubAgentContext, set_context
from lazymind.document_tools.paper import contracts, peer_review, workflow
from lazymind.document_tools.paper.review.schema import ReviewResult
from lazymind.document_tools.paper.writing import recovery, revise_document
from lazymind.document_tools.toolkits import WriterRevisionToolkit


BODY = '# Paper\n\n## Methods\nKeep methods.\n\n## Discussion\nLong discussion.'


@pytest.fixture
def manuscript():
    review = peer_review.build_output(ReviewResult(summary='Shorten discussion.', issues=[dict(
        severity='suggestion', category='language', location='Discussion', quote='Long discussion.',
        problem='Verbose discussion.', suggestion='Shorten this passage.', action_type='text_revision')],
        limitations=[]), {'topic': 'Paper', 'manuscript': BODY})
    pool = workflow.pool_from_business(dict(
        topic='Paper', manuscript=BODY, review=review['review'], review_data=review['review_data']))
    pool['selected_issue_ids'] = ['R1']
    return pool


@pytest.fixture
def editor(monkeypatch):
    shared = WriterRevisionToolkit()
    ref = {'heading_path': ['Paper', 'Discussion']}
    editor = SimpleNamespace(
        locate_revision_target=Mock(return_value=json.dumps(dict(target_title=False, targets=[dict(
            content_ref=ref, reason='Shorten discussion.')]))),
        generate_modify_plan=Mock(return_value=json.dumps(dict(scope='document', instructions=[dict(
            content_ref=ref, modify_type='update', target_scope='section', instruction='Shorten discussion.',
            meta={'issue_ids': ['R1']})]))),
        generate_string_replace_set=Mock(return_value=json.dumps(dict(replacements=[dict(
            content_ref=ref, old_string='Long discussion.', new_string='Short discussion.')]))),
        apply_string_replace=Mock(wraps=shared.apply_string_replace))
    monkeypatch.setattr(revise_document, 'WriterRevisionToolkit', lambda: editor)
    monkeypatch.setattr(recovery, 'AutoModel', lambda **_: lambda _: '{}')
    return editor


@pytest.mark.parametrize('fault', ['locate', 'plan', 'patch', 'apply', 'post_review', 'no_change'])
def test_rejected_optional_revision_keeps_original_and_pending_review(manuscript, editor, monkeypatch, fault):
    original = copy.deepcopy(manuscript)
    if fault == 'locate':
        editor.locate_revision_target.side_effect = TimeoutError('provider timeout')
    elif fault == 'plan':
        editor.generate_modify_plan.return_value = '{bad json'
    elif fault == 'patch':
        editor.generate_string_replace_set.return_value = json.dumps(dict(replacements=[dict(
            content_ref={'heading_path': ['Paper', 'Discussion']},
            old_string='Missing passage.', new_string='Changed.')]))
    elif fault == 'apply':
        editor.apply_string_replace.side_effect = RuntimeError('rejected candidate')
    elif fault == 'no_change':
        editor.generate_string_replace_set.return_value = editor.generate_string_replace_set.return_value.replace(
            'Short discussion.', 'Long discussion.')
    monkeypatch.setattr(peer_review, 'run', Mock(side_effect=TimeoutError('post-review timeout')))
    result = workflow.execute_step('revise_document', manuscript, '按当前审稿意见修订')
    assert result['status'] == 'completed'
    assert workflow.material(result['pool'], 'manuscript')['content'] == BODY
    saved_review = workflow.material(result['pool'], 'review_data')['content']
    assert saved_review == workflow.material(original, 'review_data')['content']
    assert workflow.material(result['pool'], 'review')['content'] == workflow.material(original, 'review')['content']
    assert result['pool']['selected_issue_ids'] == []
    assert manuscript == original
    if fault == 'post_review':
        assert editor.apply_string_replace.called
        peer_review.run.assert_called_once()


def test_optional_revision_does_not_swallow_cancellation(manuscript, editor):
    editor.locate_revision_target.side_effect = CancelledError()
    with pytest.raises(CancelledError):
        workflow.execute_step('revise_document', manuscript, '按当前审稿意见修订')


def test_direct_edit_reports_execution_errors(manuscript, monkeypatch):
    manuscript['selected_issue_ids'] = []
    monkeypatch.setattr(workflow, 'run_algorithm', Mock(side_effect=RuntimeError('Implementation error')))
    with pytest.raises(RuntimeError, match='Implementation error'):
        workflow.execute_step('revise_document', manuscript, 'Change the title to A New Title')
    assert workflow.material(manuscript, 'manuscript')['content'] == BODY


def test_optional_review_timeout_keeps_the_draft_and_has_no_verified_claims(monkeypatch):
    pool = workflow.pool_from_business(dict(topic='Paper', manuscript=BODY))
    monkeypatch.setattr(peer_review, 'AutoModel', Mock(side_effect=TimeoutError('review provider timeout')))
    result = workflow.execute_step('peer_review', pool, '审稿')
    assert result['status'] == 'completed'
    assert workflow.material(result['pool'], 'manuscript')['content'] == BODY
    data = workflow.material(result['pool'], 'review_data')['content']
    assert data['issues'] == [] and data['fact_claims'] == [] and data['fact_checks'] == []


def test_retained_manuscript_without_review_has_matching_unverified_metadata():
    result = revise_document.retain_manuscript(dict(manuscript=BODY, papers=[], charts=[]))
    assert result['manuscript'] == BODY and result['review_data']['issues'] == []
    assert contracts.validate_output('revise_document', result) == result
    with pytest.raises(ValueError):
        revise_document.retain_manuscript(dict(manuscript=''))


def test_runtime_scope_failure_publishes_original_manuscript(manuscript, tmp_path, monkeypatch):
    manuscript['history'] = [dict(node='F6', step='peer_review', inputs=[], outputs=[], request='审稿')]
    manuscript['sequence'] = 1
    source = tmp_path / 'pool.json'
    source.write_text(json.dumps(manuscript))
    slots = ['revise_document_pool', 'revise_document_document', 'revision_fact_check_document']
    events = []
    old_context = lazyllm.globals.get('subagent_ctx')
    monkeypatch.setattr(revise_document, 'resolve_review_issues', Mock(side_effect=ValueError('bad scope response')))
    monkeypatch.setattr(revise_document, 'run', Mock(side_effect=AssertionError('unresolved revision was executed')))
    monkeypatch.setattr(lazyllm, 'AutoModel', Mock(side_effect=AssertionError('unexpected model call')))
    params = dict(step_id='revise_document', current_user_input='继续',
                  remote_inputs={'seed_pool': str(source)}, output_slot_types=dict.fromkeys(slots, 'file'))
    set_context(SubAgentContext(
        task_id='optional-revision', conversation_id='test', agent_type='workflow_step',
        objective='Continue', params=params,
        workspace_path=str(tmp_path), input_slots=['seed_pool'], output_slots=slots, db=None, emit=events.append))
    try:
        assert workflow.run_paper_step()['status'] == 'completed'
        artifacts = {e['slot']: e['value'] for e in events if e['type'] == 'artifact'}
        assert Path(artifacts['revise_document_document']['path']).read_text() == BODY
        saved = workflow._read_bound(artifacts['revise_document_pool']['path'])
        saved_review = workflow.material(saved, 'review_data')['content']
        assert saved_review == workflow.material(manuscript, 'review_data')['content']
    finally:
        if old_context is None:
            lazyllm.globals.pop('subagent_ctx', None)
        else:
            set_context(old_context)
