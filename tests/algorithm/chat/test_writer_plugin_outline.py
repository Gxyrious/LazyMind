from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


_ROOT = Path(__file__).resolve().parents[3]
_TOOLS_PATH = _ROOT / 'workflows' / 'writer-workflow' / 'scripts' / 'tools.py'


def _load_tools_module() -> ModuleType:
    module_name = 'writer_workflow_tools_outline_test'
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, _TOOLS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_outline_workspace_generate_preserves_existing_chain(monkeypatch):
    tools = _load_tools_module()
    calls = []
    monkeypatch.setattr(
        tools,
        'writer_generate_outline',
        lambda **kwargs: calls.append(('generate', kwargs)) or '/tmp/outline.md',
    )
    monkeypatch.setattr(
        tools,
        'writer_update_writing_context',
        lambda **kwargs: calls.append(('context', kwargs)) or '/tmp/context.json',
    )

    result = tools.writer_outline_workspace(
        operation='generate',
        writing_task_path='/tmp/task.json',
        writing_context_path='/tmp/base-context.json',
    )

    assert calls == [
        ('generate', {
            'writing_task_path': '/tmp/task.json',
            'writing_context_path': '/tmp/base-context.json',
        }),
        ('context', {
            'content_artifact_path': '/tmp/outline.md',
            'writing_context_path': '/tmp/base-context.json',
        }),
    ]
    assert result == {
        'operation': 'generate',
        'outline_document': '/tmp/outline.md',
        'writing_context_after_outline': '/tmp/context.json',
    }


def test_outline_workspace_use_source_preserves_existing_chain(monkeypatch):
    tools = _load_tools_module()
    calls = []
    monkeypatch.setattr(
        tools,
        'writer_prepare_outline',
        lambda path: calls.append(('prepare', path)) or '/tmp/outline.lmd',
    )
    monkeypatch.setattr(
        tools,
        'writer_update_writing_context',
        lambda **kwargs: calls.append(('context', kwargs)) or '/tmp/context.json',
    )

    result = tools.writer_outline_workspace(
        operation='use_source',
        source_document_path='/tmp/source.lmd',
        writing_context_path='/tmp/base-context.json',
    )

    assert calls == [
        ('prepare', '/tmp/source.lmd'),
        ('context', {
            'content_artifact_path': '/tmp/outline.lmd',
            'writing_context_path': '/tmp/base-context.json',
        }),
    ]
    assert result == {
        'operation': 'use_source',
        'outline_document': '/tmp/outline.lmd',
        'writing_context_after_outline': '/tmp/context.json',
    }


def test_outline_workspace_revision_preserves_all_artifacts_and_cloud_result(
    monkeypatch,
):
    tools = _load_tools_module()
    calls = []
    monkeypatch.setattr(
        tools,
        'writer_build_revision_task',
        lambda **kwargs: calls.append(('task', kwargs)) or '/tmp/revision-task.json',
    )
    monkeypatch.setattr(
        tools,
        'writer_locate_revision_target',
        lambda **kwargs: calls.append(('locate', kwargs)) or '/tmp/locate.json',
    )
    monkeypatch.setattr(
        tools,
        'writer_generate_modify_plan',
        lambda **kwargs: calls.append(('plan', kwargs)) or '/tmp/plan.json',
    )
    monkeypatch.setattr(
        tools,
        'writer_generate_revision_set',
        lambda **kwargs: calls.append(('set', kwargs)) or '/tmp/revision-set.json',
    )
    monkeypatch.setattr(
        tools,
        'writer_apply_revision',
        lambda **kwargs: calls.append(('apply', kwargs)) or {
            'outline_document': '/tmp/revised-outline.lmd',
            'revision_result': '/tmp/revision-result.json',
            'write_result': '/tmp/write-result.json',
        },
    )
    monkeypatch.setattr(
        tools,
        'writer_update_writing_context',
        lambda **kwargs: calls.append(('context', kwargs)) or '/tmp/context.json',
    )

    result = tools.writer_outline_workspace(
        operation='revise',
        user_input='调整第二节结构',
        outline_document_path='/tmp/base-outline.lmd',
        writing_context_path='/tmp/base-context.json',
    )

    assert calls == [
        ('task', {
            'query': '调整第二节结构',
            'base_document_path': '/tmp/base-outline.lmd',
        }),
        ('locate', {
            'base_document_path': '/tmp/base-outline.lmd',
            'writing_context_path': '/tmp/base-context.json',
            'revision_task_path': '/tmp/revision-task.json',
        }),
        ('plan', {
            'base_document_path': '/tmp/base-outline.lmd',
            'writing_context_path': '/tmp/base-context.json',
            'revision_task_path': '/tmp/revision-task.json',
            'locate_result_path': '/tmp/locate.json',
        }),
        ('set', {
            'base_document_path': '/tmp/base-outline.lmd',
            'writing_context_path': '/tmp/base-context.json',
            'modify_plan_path': '/tmp/plan.json',
        }),
        ('apply', {
            'base_document_path': '/tmp/base-outline.lmd',
            'writing_context_path': '/tmp/base-context.json',
            'revision_set_path': '/tmp/revision-set.json',
        }),
        ('context', {
            'content_artifact_path': '/tmp/revised-outline.lmd',
            'writing_context_path': '/tmp/base-context.json',
        }),
    ]
    assert result == {
        'operation': 'revise',
        'outline_revision_task': '/tmp/revision-task.json',
        'outline_locate_result': '/tmp/locate.json',
        'outline_modify_plan': '/tmp/plan.json',
        'outline_revision_set': '/tmp/revision-set.json',
        'outline_revision_result': '/tmp/revision-result.json',
        'outline_write_result': '/tmp/write-result.json',
        'outline_document': '/tmp/revised-outline.lmd',
        'writing_context_after_outline': '/tmp/context.json',
    }


def test_outline_workspace_omits_empty_write_result(monkeypatch):
    tools = _load_tools_module()
    monkeypatch.setattr(tools, 'writer_build_revision_task', lambda **_kwargs: 'task')
    monkeypatch.setattr(tools, 'writer_locate_revision_target', lambda **_kwargs: 'locate')
    monkeypatch.setattr(tools, 'writer_generate_modify_plan', lambda **_kwargs: 'plan')
    monkeypatch.setattr(tools, 'writer_generate_revision_set', lambda **_kwargs: 'set')
    monkeypatch.setattr(
        tools,
        'writer_apply_revision',
        lambda **_kwargs: {
            'outline_document': 'outline.md',
            'revision_result': 'result.json',
            'write_result': '',
        },
    )
    monkeypatch.setattr(
        tools,
        'writer_update_writing_context',
        lambda **_kwargs: 'context.json',
    )

    result = tools.writer_outline_workspace(
        operation='revise',
        user_input='润色开头',
        outline_document_path='base.md',
        writing_context_path='base-context.json',
    )

    assert 'outline_write_result' not in result
    assert result['outline_document'] == 'outline.md'


def test_outline_workspace_rejects_incomplete_branch_arguments():
    tools = _load_tools_module()
    invalid_calls = [
        {'operation': 'unknown', 'writing_context_path': 'context.json'},
        {'operation': 'generate', 'writing_context_path': 'context.json'},
        {'operation': 'use_source', 'writing_context_path': 'context.json'},
        {
            'operation': 'revise',
            'writing_context_path': 'context.json',
            'outline_document_path': 'outline.md',
        },
    ]

    for arguments in invalid_calls:
        try:
            tools.writer_outline_workspace(**arguments)
        except ValueError:
            continue
        raise AssertionError(f'expected ValueError for {arguments!r}')


def test_outline_workspace_retry_resumes_after_generated_outline(
    monkeypatch,
    tmp_path,
):
    tools = _load_tools_module()
    checkpoint = tmp_path / 'task.json'
    monkeypatch.setattr(
        tools,
        '_outline_workspace_checkpoint_path',
        lambda _fingerprint: checkpoint,
    )
    outline = tmp_path / 'outline.md'
    context = tmp_path / 'context.json'
    calls = {'generate': 0, 'context': 0}

    def generate(**_kwargs):
        calls['generate'] += 1
        outline.write_text('# Outline', encoding='utf-8')
        return str(outline)

    def update_context(**_kwargs):
        calls['context'] += 1
        if calls['context'] == 1:
            raise RuntimeError('transient context failure')
        context.write_text('{}', encoding='utf-8')
        return str(context)

    monkeypatch.setattr(tools, 'writer_generate_outline', generate)
    monkeypatch.setattr(tools, 'writer_update_writing_context', update_context)
    arguments = {
        'operation': 'generate',
        'writing_task_path': '/tmp/task.json',
        'writing_context_path': '/tmp/base-context.json',
    }

    try:
        tools.writer_outline_workspace(**arguments)
    except RuntimeError as exc:
        assert str(exc) == 'transient context failure'
    else:
        raise AssertionError('expected the first context update to fail')
    assert checkpoint.exists()
    result = tools.writer_outline_workspace(**arguments)

    assert calls == {'generate': 1, 'context': 2}
    assert result['outline_document'] == str(outline)
    assert result['writing_context_after_outline'] == str(context)


def test_outline_workspace_retry_does_not_repeat_cloud_revision(
    monkeypatch,
    tmp_path,
):
    tools = _load_tools_module()
    checkpoint = tmp_path / 'task.json'
    monkeypatch.setattr(
        tools,
        '_outline_workspace_checkpoint_path',
        lambda _fingerprint: checkpoint,
    )
    paths = {}
    for name in (
        'task',
        'locate',
        'plan',
        'set',
        'outline',
        'revision-result',
        'write-result',
        'context',
    ):
        path = tmp_path / f'{name}.json'
        paths[name] = str(path)
    calls = {
        'task': 0,
        'locate': 0,
        'plan': 0,
        'set': 0,
        'apply': 0,
        'context': 0,
    }

    def artifact(name):
        def create(**_kwargs):
            calls[name] += 1
            Path(paths[name]).write_text('{}', encoding='utf-8')
            return paths[name]
        return create

    monkeypatch.setattr(tools, 'writer_build_revision_task', artifact('task'))
    monkeypatch.setattr(tools, 'writer_locate_revision_target', artifact('locate'))
    monkeypatch.setattr(tools, 'writer_generate_modify_plan', artifact('plan'))
    monkeypatch.setattr(tools, 'writer_generate_revision_set', artifact('set'))

    def apply(**_kwargs):
        calls['apply'] += 1
        for name in ('outline', 'revision-result', 'write-result'):
            Path(paths[name]).write_text('{}', encoding='utf-8')
        return {
            'outline_document': paths['outline'],
            'revision_result': paths['revision-result'],
            'write_result': paths['write-result'],
        }

    def update_context(**_kwargs):
        calls['context'] += 1
        if calls['context'] == 1:
            raise RuntimeError('transient context failure')
        Path(paths['context']).write_text('{}', encoding='utf-8')
        return paths['context']

    monkeypatch.setattr(tools, 'writer_apply_revision', apply)
    monkeypatch.setattr(tools, 'writer_update_writing_context', update_context)
    arguments = {
        'operation': 'revise',
        'user_input': '调整第二节',
        'outline_document_path': '/tmp/base-outline.lmd',
        'writing_context_path': '/tmp/base-context.json',
    }

    try:
        tools.writer_outline_workspace(**arguments)
    except RuntimeError as exc:
        assert str(exc) == 'transient context failure'
    else:
        raise AssertionError('expected the first context update to fail')
    assert checkpoint.exists()
    result = tools.writer_outline_workspace(**arguments)

    assert calls == {
        'task': 1,
        'locate': 1,
        'plan': 1,
        'set': 1,
        'apply': 1,
        'context': 2,
    }
    assert result['outline_write_result'] == paths['write-result']
    assert result['writing_context_after_outline'] == paths['context']

    repeated = tools.writer_outline_workspace(**arguments)
    assert repeated == result
    assert calls == {
        'task': 1,
        'locate': 1,
        'plan': 1,
        'set': 1,
        'apply': 1,
        'context': 2,
    }
