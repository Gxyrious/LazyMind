"""Writer-plugin tools.  Each tool reads upstream artifact files by path
(absolute or workspace-relative, as returned by get_artifact) and writes
outputs to the SubAgent workspace, returning the output file's absolute
path.  The LLM commits outputs at step end via
save_artifact(content_type='file', value=<path>).  See
docs/WriterAgent-Design.md for the v5 data models these mirror.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

from lazyllm import LOG

from lazymind.chat.engine.subagent.context import require_context
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


def _workspace_root() -> Path:
    ctx = require_context()
    return Path(ctx.workspace_path) if ctx.workspace_path else Path('/tmp')


def _new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:10]}'


def _load_mock(name: str) -> Any:
    with open(_MOCK_DIR / name, 'r', encoding='utf-8') as fh:
        return json.load(fh).get('data') or json.load(fh)


def _read_text(name: str) -> str:
    return (_MOCK_DIR / name).read_text(encoding='utf-8')


def _write_artifact_file(key: str, payload: Any) -> str:
    path = _workspace_root() / f'{key}.json'
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    LOG.info(f'[writer-tool] wrote artifact file key={key} path={path} size={len(text)} content={text}')
    return str(path)


def _read_json(path: str) -> Any:
    LOG.info(f'[writer-tool] _read_json begin path={path} exists={os.path.exists(path)}')
    if not os.path.exists(path):
        LOG.error(f'[writer-tool] _read_json FILE NOT FOUND path={path}')
        raise FileNotFoundError(path)
    with open(path, 'r', encoding='utf-8') as fh:
        raw = fh.read()
    try:
        data = json.loads(raw)
    except ValueError:
        LOG.error(f'[writer-tool] _read_json INVALID JSON path={path} raw={raw}')
        raise
    LOG.info(f'[writer-tool] _read_json OK path={path} content={raw}')
    return data


def _load_section_bundles() -> List[Dict[str, Any]]:
    s1 = _load_mock('mock_draft_section_1.json')
    s2 = _load_mock('mock_draft_section_2.json')
    return s1['sections'] + s2['sections']


def profile_resources(query: str) -> str:
    """识别输入资源的写作角色，产出 resource_profiles artifact 的本地文件。

    Args:
        query: 用户原始写作请求（来自 user_input）。

    Returns:
        resource_profiles 文件的绝对路径。请在 step 末尾对 resource_profiles key
        调 save_artifact(content_type='file', value=<此路径>) 以完成落库。
    """
    return _write_artifact_file('resource_profiles', [])


def create_writing_context(resource_profiles_path: str, query: str) -> str:
    """基于 resource_profiles 初始化 WritingContext，产出 writing_context artifact 的本地文件。

    Args:
        resource_profiles_path: 上一工具返回的 resource_profiles 文件绝对路径。
        query: 用户原始写作请求（用于主题解析）。

    Returns:
        writing_context 文件的绝对路径。请在 step 末尾对 writing_context key
        调 save_artifact(content_type='file', value=<此路径>) 以完成落库。
    """
    LOG.info(f'[writer-tool] create_writing_context input resource_profiles_path={resource_profiles_path}')
    _read_json(resource_profiles_path)
    ctx = WritingContext(**_load_mock('mock_writing_context.json')).model_dump(mode='json')
    return _write_artifact_file('writing_context', ctx)


def generate_outline(writing_context_path: str) -> str:
    """基于 WritingContext 生成结构化大纲，产出 outline artifact 的本地文件。

    Args:
        writing_context_path: writing_context 文件路径（绝对路径或 workspace 相对路径）。

    Returns:
        outline 文件的绝对路径。请在 step 末尾对 outline key
        调 save_artifact(content_type='file', value=<此路径>) 以完成落库。
    """
    LOG.info(f'[writer-tool] generate_outline input writing_context_path={writing_context_path}')
    _read_json(writing_context_path)
    outline = WritingOutline(**_load_mock('mock_outline.json')).model_dump(mode='json')
    return _write_artifact_file('outline', outline)


def generate_section_instructions(outline_path: str, writing_context_path: str) -> str:
    """基于大纲为每个顶层章节生成 SectionInstruction，产出 section_instructions artifact 的本地文件。

    Args:
        outline_path: outline 文件路径（绝对路径或 workspace 相对路径）。
        writing_context_path: writing_context 文件路径（绝对路径或 workspace 相对路径）。

    Returns:
        section_instructions 文件的绝对路径。请在 step 末尾对 section_instructions key
        调 save_artifact(content_type='file', value=<此路径>) 以完成落库。
    """
    LOG.info(f'[writer-tool] generate_section_instructions input outline_path={outline_path} writing_context_path={writing_context_path}')
    _read_json(outline_path)
    _read_json(writing_context_path)
    instructions: List[Dict[str, Any]] = []
    for sec in _load_section_bundles():
        raw = dict(sec['instruction'])
        raw['outline_node_id'] = sec['outline_node_id']
        raw.setdefault('source_refs', [])
        raw.setdefault('pending_subtasks', [])
        raw.setdefault('revision_notes', [])
        raw.setdefault('meta', {})
        instructions.append(SectionInstruction(**raw).model_dump(mode='json'))
    return _write_artifact_file('section_instructions', instructions)


def generate_draft_section(section_instructions_path: str, writing_context_path: str) -> Dict[str, str]:
    """按 section_instructions 逐章生成草稿：每章写为单独文件，装配为 draft_document 文件。

    Args:
        section_instructions_path: section_instructions 文件路径（绝对路径或 workspace 相对路径）。
        writing_context_path: writing_context 文件路径（绝对路径或 workspace 相对路径）。

    Returns:
        包含 draft_sections_path 和 draft_document_path 的 dict。请在 step 末尾分别对
        draft_sections 和 draft_document 两个 key 各调一次
        save_artifact(content_type='file', value=<对应路径>) 以完成落库。
    """
    LOG.info(f'[writer-tool] generate_draft_section input section_instructions_path={section_instructions_path} writing_context_path={writing_context_path}')
    instructions = _read_json(section_instructions_path)
    _read_json(writing_context_path)
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
        sections.append(sec_obj.model_dump(mode='json'))

    sections_path = _write_artifact_file('draft_sections', sections)
    outline = _load_mock('mock_outline.json')
    draft_doc = {
        'draft_id': _new_id('dft'),
        'title': outline.get('title', ''),
        'sections': sections,
    }
    document_path = _write_artifact_file('draft_document', draft_doc)
    return {'draft_sections_path': sections_path, 'draft_document_path': document_path}


def check_consistency(draft_path: str, writing_context_path: str) -> str:
    """对草稿做一致性/质量审阅，产出 review_report artifact 的本地文件。

    Args:
        draft_path: draft_document 文件路径（绝对路径或 workspace 相对路径）。
        writing_context_path: writing_context 文件路径（绝对路径或 workspace 相对路径）。

    Returns:
        review_report 文件的绝对路径。请在 step 末尾对 review_report key
        调 save_artifact(content_type='file', value=<此路径>) 以完成落库。
    """
    LOG.info(f'[writer-tool] check_consistency input draft_path={draft_path} writing_context_path={writing_context_path}')
    _read_json(draft_path)
    _read_json(writing_context_path)
    audit = AuditResult(**_load_mock('mock_review_report.json')).model_dump(mode='json')
    report = {
        'report_id': _new_id('rep'),
        'target': 'draft_document',
        'result': audit,
        'meta': {},
    }
    return _write_artifact_file('review_report', report)


def generate_writing_output(
    draft_path: str, review_report_path: str, writing_context_path: str,
) -> str:
    """基于草稿和审阅报告产出最终成稿，产出 writing_output artifact 的本地文件。

    Args:
        draft_path: draft_document 文件路径（绝对路径或 workspace 相对路径）。
        review_report_path: review_report 文件路径（绝对路径或 workspace 相对路径）。
        writing_context_path: writing_context 文件路径（绝对路径或 workspace 相对路径）。

    Returns:
        writing_output 文件的绝对路径。请在 step 末尾对 writing_output key
        调 save_artifact(content_type='file', value=<此路径>) 以完成落库。
    """
    LOG.info(f'[writer-tool] generate_writing_output input draft_path={draft_path} review_report_path={review_report_path} writing_context_path={writing_context_path}')
    draft = _read_json(draft_path)
    _read_json(review_report_path)
    _read_json(writing_context_path)
    output_ = WritingOutput(
        output_id=_new_id('out'),
        title=draft.get('title', ''),
        content=_read_text('mock_writing_output.md'),
        output_format='markdown',
        references=[],
        meta={},
    ).model_dump(mode='json')
    return _write_artifact_file('writing_output', output_)