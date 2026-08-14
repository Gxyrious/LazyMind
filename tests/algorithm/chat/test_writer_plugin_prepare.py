from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


_ROOT = Path(__file__).resolve().parents[3]
_TOOLS_PATH = _ROOT / 'workflows' / 'writer-workflow' / 'scripts' / 'tools.py'


def _load_tools_module() -> ModuleType:
    module_name = 'writer_workflow_tools_prepare_test'
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, _TOOLS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _stub_prepare_chain(monkeypatch, tools, tmp_path):
    calls = []

    def result(name):
        path = tmp_path / f'{name}.json'
        path.write_text('{}', encoding='utf-8')
        return str(path)

    monkeypatch.setattr(
        tools,
        'writer_build_writing_task',
        lambda **kwargs: calls.append(('task', kwargs)) or result('task'),
    )
    monkeypatch.setattr(
        tools,
        'writer_collect_available_media',
        lambda **kwargs: calls.append(('media', kwargs)) or {
            'media_assets': result('media'),
            'profile_input_resources': result('profile-inputs'),
            'warnings': [],
        },
    )
    monkeypatch.setattr(
        tools,
        'writer_profile_resources',
        lambda **kwargs: calls.append(('profiles', kwargs)) or result('profiles'),
    )
    monkeypatch.setattr(
        tools,
        'writer_create_writing_context',
        lambda **kwargs: calls.append(('context', kwargs)) or result('context'),
    )
    return calls


def test_prepare_workspace_from_scratch_runs_one_fixed_chain(monkeypatch, tmp_path):
    tools = _load_tools_module()
    calls = _stub_prepare_chain(monkeypatch, tools, tmp_path)
    monkeypatch.setattr(
        tools,
        'require_context',
        lambda: SimpleNamespace(params={'history_files_per_turn': {}}),
    )

    prepared = tools.writer_prepare_workspace(
        user_input='写一篇 1500 字左右的《AI Agent 可观测性实践》',
        operation='create',
    )

    assert [name for name, _ in calls] == ['task', 'media', 'profiles', 'context']
    assert calls[0][1]['representation'] == 'markdown'
    assert prepared['next_step'] == 'outline'
    assert prepared['representation'] == 'markdown'
    assert 'source_document' not in prepared
    assert 'target_document' not in prepared


def test_prepare_workspace_uses_local_outline_without_cloud_load(monkeypatch, tmp_path):
    tools = _load_tools_module()
    calls = _stub_prepare_chain(monkeypatch, tools, tmp_path)
    source = tmp_path / 'outline.lmd'
    source.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(
        tools,
        'require_context',
        lambda: SimpleNamespace(
            params={'history_files_per_turn': {'turn-1': [str(source)]}},
        ),
    )
    monkeypatch.setattr(tools, 'writer_load_local_document', lambda _name: str(source))
    monkeypatch.setattr(
        tools,
        'writer_load_document',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('cloud load')),
    )

    prepared = tools.writer_prepare_workspace(
        user_input='使用这份大纲写作',
        operation='use_outline',
        source_filename='outline.lmd',
    )

    assert calls[0][1]['representation'] == 'ir'
    assert prepared['source_document'] == str(source)
    assert prepared['next_step'] == 'outline'


def test_prepare_workspace_loads_cloud_revision_as_draft(monkeypatch, tmp_path):
    tools = _load_tools_module()
    calls = _stub_prepare_chain(monkeypatch, tools, tmp_path)
    monkeypatch.setattr(
        tools,
        'require_context',
        lambda: SimpleNamespace(params={'history_files_per_turn': {}}),
    )
    source = tmp_path / 'source.lmd'
    target = tmp_path / 'target.json'
    source.write_text('{}', encoding='utf-8')
    target.write_text('{}', encoding='utf-8')
    load_calls = []
    monkeypatch.setattr(
        tools,
        'writer_load_document',
        lambda **kwargs: load_calls.append(kwargs) or {
            'source_document': str(source),
            'target_document': str(target),
        },
    )

    prepared = tools.writer_prepare_workspace(
        user_input='修改 https://example.feishu.cn/docx/example 的第二节',
        operation='revise_document',
    )

    assert load_calls == [{
        'user_input': '修改 https://example.feishu.cn/docx/example 的第二节',
        'stage': 'draft',
    }]
    assert calls[0][1]['representation'] == 'ir'
    assert prepared['source_document'] == str(source)
    assert prepared['target_document'] == str(target)
    assert prepared['next_step'] == 'write_document'


def test_prepare_workspace_prefers_explicit_cloud_source_over_reference_file(
    monkeypatch,
    tmp_path,
):
    tools = _load_tools_module()
    _stub_prepare_chain(monkeypatch, tools, tmp_path)
    reference = tmp_path / 'reference.md'
    reference.write_text('# Reference', encoding='utf-8')
    monkeypatch.setattr(
        tools,
        'require_context',
        lambda: SimpleNamespace(
            params={'history_files_per_turn': {'turn-1': [str(reference)]}},
        ),
    )
    source = tmp_path / 'source.lmd'
    target = tmp_path / 'target.json'
    source.write_text('{}', encoding='utf-8')
    target.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(
        tools,
        'writer_load_local_document',
        lambda *_args: (_ for _ in ()).throw(AssertionError('local load')),
    )
    monkeypatch.setattr(
        tools,
        'writer_load_document',
        lambda **_kwargs: {
            'source_document': str(source),
            'target_document': str(target),
        },
    )

    prepared = tools.writer_prepare_workspace(
        user_input='重写 https://example.feishu.cn/docx/example，附件仅作参考',
        operation='rewrite_document',
    )

    assert prepared['source_document'] == str(source)
    assert prepared['representation'] == 'ir'
