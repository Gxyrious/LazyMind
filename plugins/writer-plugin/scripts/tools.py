"""Writer-plugin tools.  Mock stage: each tool reads inputs via the framework
get_artifact and persists outputs via save_artifact.  Mock payloads live in
plugins/writer-plugin/mock/.  See docs/WriterAgent-Design.md for the v5 data
models these mirror."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

from lazymind.chat.engine.subagent.tools import get_artifact, save_artifact
from lazyllm.tools.writer.data_models import (
    AuditResult,
    DraftBlock,
    DraftSection,
    SectionInstruction,
    WritingContext,
    WritingOutline,
    WritingOutput,
)


_MOCK_DIR = Path(__file__).resolve().parent.parent / 'mock'


def _new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:10]}'


def _load_mock(name: str) -> Any:
    with open(_MOCK_DIR / name, 'r', encoding='utf-8') as fh:
        return json.load(fh).get('data') or json.load(fh)


def _read_text(name: str) -> str:
    return (_MOCK_DIR / name).read_text(encoding='utf-8')


def _load_json_artifact(key: str) -> Any:
    """Load a json artifact's data field.  Unwraps handle_tool_errors once."""
    resp = get_artifact(key=key)
    inner = (resp or {}).get('result') or {}
    if inner.get('status') != 'ok':
        raise LookupError(f"Artifact '{key}' not found: {inner.get('message', 'unknown')}")
    artifacts: list = inner.get('artifacts') or []
    if not artifacts:
        raise LookupError(f"Artifact '{key}' returned ok but has no items.")
    value = artifacts[-1].get('value') or {}
    if isinstance(value, dict) and 'data' in value:
        return value['data']
    return value


def _load_section_bundles() -> List[Dict[str, Any]]:
    s1 = _load_mock('mock_draft_section_1.json')
    s2 = _load_mock('mock_draft_section_2.json')
    return s1['sections'] + s2['sections']


def profile_resources(query: str) -> str:
    """识别输入资源的写作角色，产出 resource_profiles artifact。

    Args:
        query: 用户原始写作请求（来自 user_input）。
    """
    save_artifact(key='resource_profiles', value=[], content_type='json')
    return "saved 'resource_profiles'"


def create_writing_context(resource_profiles_key: str, query: str) -> str:
    """基于 resource_profiles 初始化 WritingContext，产出 writing_context artifact。

    Args:
        resource_profiles_key: profile_resources 产出的 artifact key。
        query: 用户原始写作请求（用于主题解析）。
    """
    _load_json_artifact(resource_profiles_key)
    ctx = WritingContext(**_load_mock('mock_writing_context.json')).model_dump(mode='json')
    save_artifact(key='writing_context', value=ctx, content_type='json')
    return "saved 'writing_context'"


def generate_outline(writing_context_key: str) -> str:
    """基于 WritingContext 生成结构化大纲，产出 outline artifact。

    Args:
        writing_context_key: writing_context 的 artifact key。
    """
    _load_json_artifact(writing_context_key)
    outline_dict = _load_mock('mock_outline.json')
    outline = WritingOutline(**outline_dict).model_dump(mode='json')
    save_artifact(key='outline', value=outline, content_type='json')
    return "saved 'outline'"


def generate_section_instructions(outline_key: str, writing_context_key: str) -> str:
    """基于大纲为每个顶层章节生成 SectionInstruction，产出 section_instructions artifact。

    Args:
        outline_key: outline 的 artifact key。
        writing_context_key: writing_context 的 artifact key。
    """
    _load_json_artifact(outline_key)
    _load_json_artifact(writing_context_key)
    instructions: List[Dict[str, Any]] = []
    for sec in _load_section_bundles():
        raw = dict(sec['instruction'])
        raw['outline_node_id'] = sec['outline_node_id']
        # Fill the model's optional-with-default fields that mock omits.
        raw.setdefault('source_refs', [])
        raw.setdefault('pending_subtasks', [])
        raw.setdefault('revision_notes', [])
        raw.setdefault('meta', {})
        instructions.append(SectionInstruction(**raw).model_dump(mode='json'))
    save_artifact(key='section_instructions', value=instructions, content_type='json')
    return "saved 'section_instructions'"


def generate_draft_section(section_instructions_key: str, writing_context_key: str) -> str:
    """按 section_instructions 逐章生成草稿：每章存为 draft_section（list），并装配 draft。

    说明：instructions 列表对 LLM 不可见（只看到 key），因此逐章循环在本工具内部完成。

    Args:
        section_instructions_key: generate_section_instructions 产出的 artifact key。
        writing_context_key: writing_context 的 artifact key。
    """
    instructions = _load_json_artifact(section_instructions_key) or []
    _load_json_artifact(writing_context_key)
    bundles_by_node = {b['outline_node_id']: b for b in _load_section_bundles()}
    sections: List[Dict[str, Any]] = []
    for instr in instructions:
        node_id = instr['outline_node_id']
        bundle = bundles_by_node.get(node_id, {})
        draft = bundle.get('draft') or {}
        section_id = draft.get('section_id', _new_id('sec'))
        blocks_raw = draft.get('blocks', [])
        if not draft:
            blocks_raw = [{
                'block_id': _new_id('b'),
                'outline_node_id': node_id,
                'section_id': section_id,
                'heading': instr.get('section_title', '章节'),
                'content': '(mock) 该章节未在 mock 数据中找到对应大纲节点。',
                'subtasks': [],
                'meta': {},
            }]
        blocks = [
            DraftBlock(**{
                'block_id': b.get('block_id', _new_id('b')),
                'outline_node_id': node_id,
                'section_id': b.get('section_id', section_id),
                'heading': b.get('heading'),
                'content': b.get('content', ''),
                'subtasks': b.get('subtasks', []),
                'meta': b.get('meta', {}),
            }).model_dump(mode='json')
            for b in blocks_raw
        ]
        sec_obj = DraftSection(
            section_id=section_id,
            outline_node_id=node_id,
            title=draft.get('title', instr.get('section_title', '')),
            instruction_id=instr.get('instruction_id'),
            sub_sections=[],
            blocks=blocks,
            subtasks=draft.get('subtasks', []),
            meta={},
        )
        sec = sec_obj.model_dump(mode='json')
        sections.append(sec)
        save_artifact(key='draft_section', value=sec, content_type='json')
    outline = _load_mock('mock_outline.json')
    draft_doc = {
        'draft_id': _new_id('dft'),
        'title': outline.get('title', ''),
        'sections': sections,
    }
    save_artifact(key='draft', value=draft_doc, content_type='json')
    return "saved 'draft_section' (× per section) and 'draft'"


def check_consistency(draft_key: str, writing_context_key: str) -> str:
    """对草稿做一致性/质量审阅，产出 review_report artifact。

    Args:
        draft_key: draft 的 artifact key。
        writing_context_key: writing_context 的 artifact key。
    """
    _load_json_artifact(draft_key)
    _load_json_artifact(writing_context_key)
    audit_dict = _load_mock('mock_review_report.json')
    audit = AuditResult(**audit_dict).model_dump(mode='json')
    report = {
        'report_id': _new_id('rep'),
        'target': 'draft',
        'result': audit,
        'meta': {},
    }
    save_artifact(key='review_report', value=report, content_type='json')
    return "saved 'review_report'"


def generate_writing_output(
    draft_key: str, review_report_key: str, writing_context_key: str,
) -> str:
    """基于草稿和审阅报告产出最终成稿，产出 final_report artifact。

    Args:
        draft_key: draft 的 artifact key。
        review_report_key: review_report 的 artifact key。
        writing_context_key: writing_context 的 artifact key。
    """
    draft = _load_json_artifact(draft_key)
    _load_json_artifact(review_report_key)
    _load_json_artifact(writing_context_key)
    output_ = WritingOutput(
        output_id=_new_id('out'),
        title=draft.get('title', ''),
        content=_read_text('mock_writing_output.md'),
        output_format='markdown',
        references=[],
        meta={},
    ).model_dump(mode='json')
    save_artifact(key='final_report', value=output_, content_type='json')
    return "saved 'final_report'"
