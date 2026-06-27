"""Writer-plugin 工具函数。
每个工具读取上游 artifact 文件，把输出写到 SubAgent 工作区，并返回输出文件的绝对路径，与 get_artifact 的返回一致。
工具函数本身不负责落库，主 Agent 在 step 结束时调用 `save_artifact(content_type='file', value=<路径>)` 完成提交。
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict

from lazyllm import LOG

from lazymind.chat.engine.subagent.context import require_context
from lazyllm.tools.writer.data_models import (
    AuditResult,
    DraftBlock,
    DraftDocument,
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


def _write_artifact_file(key: str, payload: Any) -> str:
    path = _workspace_root() / f'{key}.json'
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    LOG.info(f'[writer-tool] wrote artifact file key={key} path={path} size={len(text)} content={text}')
    return str(path)


def _read_artifact_file(path: str) -> Any:
    LOG.info(f'[writer-tool] _read_artifact_file begin path={path} exists={os.path.exists(path)}')
    if not os.path.exists(path):
        LOG.error(f'[writer-tool] _read_artifact_file FILE NOT FOUND path={path}')
        raise FileNotFoundError(path)
    with open(path, 'r', encoding='utf-8') as fh:
        raw = fh.read()
    try:
        data = json.loads(raw)
    except ValueError:
        LOG.error(f'[writer-tool] _read_artifact_file INVALID JSON path={path} raw={raw}')
        raise
    LOG.info(f'[writer-tool] _read_artifact_file OK path={path} content={raw}')
    return data


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
    _read_artifact_file(resource_profiles_path)
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
    _read_artifact_file(writing_context_path)
    outline = WritingOutline(**_load_mock('mock_outline.json')).model_dump(mode='json')
    return _write_artifact_file('outline', outline)


def generate_section_instructions(outline_path: str, writing_context_path: str, batch: int) -> str:
    """基于大纲为一批顶层章节生成 SectionInstruction，产出本批 section_instructions artifact 的本地文件。

    本步分两批调用：batch=1 和 batch=2，每次返回不同的章节子集，调用方应分别对
    section_instructions key 各 save_artifact 一次。

    Args:
        outline_path: outline 文件路径（绝对路径或 workspace 相对路径）。
        writing_context_path: writing_context 文件路径（绝对路径或 workspace 相对路径）。
        batch: 批次号（1 或 2），决定取 mock_draft_section_{batch}.json 中的章节子集。

    Returns:
        本批 section_instructions 文件的绝对路径。请在 step 末尾对 section_instructions key
        调 save_artifact(content_type='file', value=<此路径>) 以完成落库。
    """
    LOG.info(f'[writer-tool] generate_section_instructions input outline_path={outline_path} writing_context_path={writing_context_path} batch={batch}')
    _read_artifact_file(outline_path)
    _read_artifact_file(writing_context_path)
    bundle = _load_mock(f'mock_draft_section_{batch}.json')
    instructions = [
        SectionInstruction(**{**sec['instruction'], 'outline_node_id': sec['outline_node_id']}).model_dump(mode='json')
        for sec in bundle['sections']
    ]
    return _write_artifact_file(f'section_instructions_{batch}', instructions)


def generate_draft_section(section_instructions_path: str, writing_context_path: str, batch: int) -> str:
    """按本批 section_instructions 逐章生成草稿，产出本批 draft_sections artifact 的本地文件。

    本步分两批调用：batch=1 和 batch=2，每次返回不同的章节草稿子集，调用方应分别对
    draft_sections key 各 save_artifact 一次。全部章节的合并产物由 assemble_draft_document 单独装配。

    Args:
        section_instructions_path: 本批 section_instructions 文件路径（绝对路径或 workspace 相对路径）。
        writing_context_path: writing_context 文件路径（绝对路径或 workspace 相对路径）。
        batch: 批次号（1 或 2），决定取 mock_draft_section_{batch}.json 中的章节子集。

    Returns:
        本批 draft_sections 文件的绝对路径。请在 step 末尾对 draft_sections key
        调 save_artifact(content_type='file', value=<此路径>) 以完成落库。
    """
    LOG.info(f'[writer-tool] generate_draft_section input section_instructions_path={section_instructions_path} writing_context_path={writing_context_path} batch={batch}')
    _read_artifact_file(section_instructions_path)
    _read_artifact_file(writing_context_path)
    bundle = _load_mock(f'mock_draft_section_{batch}.json')
    sections = [
        DraftSection(
            section_id=sec['draft'].get('section_id'),
            outline_node_id=sec['outline_node_id'],
            title=sec['draft'].get('title'),
            instruction_id=sec['instruction'].get('instruction_id'),
            blocks=[
                DraftBlock(**{
                    **b,
                    'outline_node_id': sec['outline_node_id'],
                    'section_id': sec['draft'].get('section_id'),
                })
                for b in sec['draft'].get('blocks', [])
            ],
            subtasks=sec['draft'].get('subtasks', []),
            meta=sec['draft'].get('meta', {}),
        ).model_dump(mode='json')
        for sec in bundle['sections']
    ]
    return _write_artifact_file(f'draft_sections_{batch}', sections)


def assemble_draft_document(draft_sections_path_1: str, draft_sections_path_2: str) -> str:
    """合并两批 draft_sections 装配出完整的 DraftDocument，产出 draft_document artifact 的本地文件。

    draft_document 是 cardinality=single 的产出，只在两批 draft_sections 都就绪后调用一次。

    Args:
        draft_sections_path_1: batch=1 的 draft_sections 文件路径（绝对路径或 workspace 相对路径）。
        draft_sections_path_2: batch=2 的 draft_sections 文件路径（绝对路径或 workspace 相对路径）。

    Returns:
        draft_document 文件的绝对路径。请在 step 末尾对 draft_document key
        调 save_artifact(content_type='file', value=<此路径>) 以完成落库。
    """
    LOG.info(f'[writer-tool] assemble_draft_document input draft_sections_path_1={draft_sections_path_1} draft_sections_path_2={draft_sections_path_2}')
    sections_1 = _read_artifact_file(draft_sections_path_1)
    sections_2 = _read_artifact_file(draft_sections_path_2)
    outline = _load_mock('mock_outline.json')
    draft_doc = DraftDocument(
        draft_id=_new_id('dft'),
        title=outline.get('title', ''),
        sections=[*sections_1, *sections_2],
        meta={},
    ).model_dump(mode='json')
    return _write_artifact_file('draft_document', draft_doc)


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
    _read_artifact_file(draft_path)
    _read_artifact_file(writing_context_path)
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
    draft = _read_artifact_file(draft_path)
    _read_artifact_file(review_report_path)
    _read_artifact_file(writing_context_path)
    output_ = WritingOutput(
        output_id=_new_id('out'),
        title=draft.get('title', ''),
        content=(_MOCK_DIR / 'mock_writing_output.md').read_text(encoding='utf-8'),
        output_format='markdown',
        references=[],
        meta={},
    ).model_dump(mode='json')
    return _write_artifact_file('writing_output', output_)
