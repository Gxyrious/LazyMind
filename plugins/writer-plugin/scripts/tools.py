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

from lazyllm import LOG, AutoModel

from lazymind.chat.engine.subagent.context import require_context
from lazyllm.tools.writer.data_models import (
    AuditResult,
    DraftBlock,
    DraftDocument,
    DraftSection,
    InputResource,
    SectionInstruction,
    WritingTask,
    WritingOutline,
    WritingOutput,
)
from lazyllm.tools.writer.tools import (
    WriterContextTools,
    WriterPlanningTools,
    WriterResourceTools,
)


_LLM_CACHE: Dict[str, Any] = {}

def _shared_llm() -> Any:
    ctx = require_context()
    key = ctx.task_id
    if key not in _LLM_CACHE:
        _LLM_CACHE[key] = AutoModel(model='llm')
    return _LLM_CACHE[key]


_MOCK_DIR = Path(__file__).resolve().parent.parent / 'mock'

def _load_mock(name: str) -> Any:
    with open(_MOCK_DIR / name, 'r', encoding='utf-8') as fh:
        raw = json.load(fh)
    return raw.get('data') if isinstance(raw, dict) else raw


def _workspace_root() -> Path:
    ctx = require_context()
    return Path(ctx.workspace_path) if ctx.workspace_path else Path('/tmp')


def _new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:10]}'


def _read_artifact_file(path: str) -> Any:
    """读取 plugin workspace 中的 artifact 文件，优先解包 Artifact 格式的 data 字段。"""
    LOG.info(f'[writer-tool] _read_artifact_file begin path={path} exists={os.path.exists(path)}')
    if not os.path.exists(path):
        LOG.error(f'[writer-tool] _read_artifact_file FILE NOT FOUND path={path}')
        raise FileNotFoundError(path)
    with open(path, 'r', encoding='utf-8') as fh:
        raw = json.load(fh)
    if isinstance(raw, dict) and 'data' in raw:
        raw = raw['data']
    LOG.info(f'[writer-tool] _read_artifact_file OK path={path} data={raw}')
    return raw


from lazyllm.tools.writer.utils import save_artifact_json


def build_writing_task(query: str) -> str:
    """构造 WritingTask 并产出 writing_task Artifact 文件。

    Args:
        query: 用户原始写作请求（来自 user_input）。

    Returns:
        writing_task Artifact 文件的绝对路径。
    """
    LOG.info(f'[writer-tool] build_writing_task input query={query!r}')
    task = WritingTask(query=query, task_type='write') # TODO: 借助LLM进行精细化的构造
    path = _workspace_root() / 'writing_task.json'
    save_artifact_json(task, str(path), created_by='build_writing_task')
    LOG.info(f'[writer-tool] build_writing_task produced writing_task artifact path={path}')
    return str(path)


def profile_resources(writing_task_path: str) -> str:
    """产出 resource_profiles Artifact 文件。

    Args:
        writing_task_path: 上一步产出的 writing_task Artifact 文件绝对路径。

    Returns:
        resource_profiles Artifact 文件的绝对路径。
    """
    LOG.info(f'[writer-tool] profile_resources input writing_task_path={writing_task_path}')
    _read_artifact_file(writing_task_path)
    ctx = require_context()
    files_by_turn = ctx.params.get('history_files_per_turn') or {}
    all_files = [p for paths in files_by_turn.values() for p in paths]
    LOG.info(f'[writer-tool] profile_resources history_files_per_turn={files_by_turn} all_files_count={len(all_files)} all_files={all_files}')
    # FIXME: 测试不同的 InputResource 在 profile_resources 中的解析情况
    input_resources = [_to_input_resource(p) for p in all_files] + [
        # InputResource(resource_id='demo_feishu_doc', resource_type='document', uri='feishu://~docx/demo-doc-1', title='飞书产品文档', summary='飞书产品规划文档，作为写作背景参考', meta={'role': 'background'}),
        # InputResource(resource_id='demo_url', resource_type='url', uri='https://example.com/product-spec', title='产品规范网页', summary='介绍本产品的核心功能与目标用户群体', meta={'role': 'spec', 'template': 'structure'}),
        # InputResource(resource_id='demo_kb', resource_type='kb', kb_id='kb-demo-001', title='品牌术语知识库', summary='公司品牌术语表，写作时需遵守', meta={'role': 'spec'}),
    ]
    LOG.info(f'[writer-tool] profile_resources input_resources={[r.model_dump() for r in input_resources]}')
    result = WriterResourceTools(
        llm=_shared_llm(),
        artifact_store=str(_workspace_root()),
    ).profile_resources(task=writing_task_path, input_resources=input_resources)
    LOG.info(f'[writer-tool] profile_resources produced resource_profiles artifact counts={result["metadata"]["counts"]}')
    return result['artifact_path']


def _to_input_resource(abs_path: str) -> Any:
    """从绝对路径构造 InputResource，默认 resource_type='file'（writer 用 SimpleDirectoryReader 读）。"""
    return InputResource(
        resource_id=os.path.basename(abs_path),
        resource_type='file',
        uri=abs_path,
        title=os.path.basename(abs_path),
        mime_type=None,
        summary=None,
        meta={},
    )


def create_writing_context(writing_task_path: str, resource_profiles_path: str) -> str:
    """产出 writing_context Artifact 文件。

    Args:
        writing_task_path: writing_task Artifact 文件绝对路径。
        resource_profiles_path: resource_profiles Artifact 文件绝对路径。

    Returns:
        writing_context Artifact 文件的绝对路径。
    """
    LOG.info(f'[writer-tool] create_writing_context input writing_task_path={writing_task_path} resource_profiles_path={resource_profiles_path}')
    _read_artifact_file(writing_task_path)
    _read_artifact_file(resource_profiles_path)
    result = WriterContextTools(
        llm=None,
        artifact_store=str(_workspace_root()),
    ).create_writing_context(task=writing_task_path, resource_profiles=resource_profiles_path)
    LOG.info(f'[writer-tool] create_writing_context produced writing_context artifact {result}')
    return result['artifact_path']


def generate_outline(writing_task_path: str, writing_context_path: str) -> str:
    """产出 outline Artifact 文件。

    Args:
        writing_task_path: writing_task Artifact 文件绝对路径。
        writing_context_path: writing_context Artifact 文件绝对路径。

    Returns:
        outline Artifact 文件的绝对路径。
    """
    LOG.info(f'[writer-tool] generate_outline input writing_task_path={writing_task_path} writing_context_path={writing_context_path}')
    _read_artifact_file(writing_task_path)
    _read_artifact_file(writing_context_path)
    result = WriterPlanningTools(
        llm=_shared_llm(),
        artifact_store=str(_workspace_root()),
    ).generate_outline(task=writing_task_path, context=writing_context_path)
    LOG.info(f'[writer-tool] generate_outline produced outline artifact {result}')
    return result['artifact_path']


def generate_section_instructions(outline_path: str, writing_context_path: str) -> str:
    """产出 section_instructions Artifact 文件（包含完整 SectionInstructionList）。

    Args:
        outline_path: outline Artifact 文件绝对路径。
        writing_context_path: writing_context Artifact 文件绝对路径。

    Returns:
        section_instructions Artifact 文件的绝对路径。
    """
    LOG.info(f'[writer-tool] generate_section_instructions input outline_path={outline_path} writing_context_path={writing_context_path}')
    _read_artifact_file(outline_path)
    _read_artifact_file(writing_context_path)
    result = WriterPlanningTools(
        llm=_shared_llm(),
        artifact_store=str(_workspace_root()),
    ).generate_section_instructions(outline=outline_path, context=writing_context_path)
    LOG.info(f'[writer-tool] generate_section_instructions produced section_instructions artifact {result}')
    return result['artifact_path']


def generate_draft_section(section_instructions_path: str, writing_context_path: str, batch: int) -> str:
    """按 batch=1/2 产出本批 draft_sections Artifact 文件。

    Args:
        section_instructions_path: 本批 section_instructions 文件路径。
        writing_context_path: writing_context 文件路径。
        batch: 批次号（1 或 2）。

    Returns:
        draft_sections 文件的绝对路径。
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
        )
        for sec in bundle['sections']
    ]
    path = str(_workspace_root() / f'draft_sections_{batch}.json')
    return save_artifact_json(sections, path, created_by='generate_draft_section')


def assemble_draft_document(draft_sections_path_1: str, draft_sections_path_2: str) -> str:
    """合并两批 draft_sections 产出 draft_document Artifact 文件。

    Args:
        draft_sections_path_1: batch=1 的 draft_sections 文件路径。
        draft_sections_path_2: batch=2 的 draft_sections 文件路径。

    Returns:
        draft_document 文件的绝对路径。
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
    )
    path = str(_workspace_root() / 'draft_document.json')
    return save_artifact_json(draft_doc, path, created_by='assemble_draft_document')


def check_consistency(draft_path: str, writing_context_path: str) -> str:
    """产出 review_report Artifact 文件。

    Args:
        draft_path: draft_document 文件路径。
        writing_context_path: writing_context 文件路径。

    Returns:
        review_report 文件的绝对路径。
    """
    LOG.info(f'[writer-tool] check_consistency input draft_path={draft_path} writing_context_path={writing_context_path}')
    _read_artifact_file(draft_path)
    _read_artifact_file(writing_context_path)
    audit = AuditResult(**_load_mock('mock_review_report.json'))
    report = {
        'report_id': _new_id('rep'),
        'target': 'draft_document',
        'result': audit,
        'meta': {},
    }
    path = str(_workspace_root() / 'review_report.json')
    return save_artifact_json(report, path, created_by='check_consistency')


def generate_writing_output(
    draft_path: str, review_report_path: str, writing_context_path: str,
) -> str:
    """产出 writing_output Artifact 文件。

    Args:
        draft_path: draft_document 文件路径。
        review_report_path: review_report 文件路径。
        writing_context_path: writing_context 文件路径。

    Returns:
        writing_output 文件的绝对路径。
    """
    LOG.info(f'[writer-tool] generate_writing_output input draft_path={draft_path} review_report_path={review_report_path} writing_context_path={writing_context_path}')
    draft = _read_artifact_file(draft_path)
    _read_artifact_file(review_report_path)
    _read_artifact_file(writing_context_path)
    output_ = WritingOutput(
        output_id=_new_id('out'),
        title=draft.get('title', '') if isinstance(draft, dict) else getattr(draft, 'title', ''),
        content=(_MOCK_DIR / 'mock_writing_output.md').read_text(encoding='utf-8'),
        output_format='markdown',
        references=[],
        meta={},
    )
    path = str(_workspace_root() / 'writing_output.json')
    return save_artifact_json(output_, path, created_by='generate_writing_output')
