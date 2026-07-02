"""Writer-plugin 工具函数。
每个工具读取上游 artifact 文件，把输出写到 SubAgent 工作区，并返回输出文件的绝对路径，与 get_artifact 的返回一致。
工具函数本身不负责落库，主 Agent 在 step 结束时调用 `save_artifact(content_type='file', value=<路径>)` 完成提交。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from lazyllm import LOG, AutoModel

from lazymind.chat.engine.subagent.context import require_context
from lazyllm.tools.writer.data_models import (
    InputResource,
    SectionInstruction,
    WritingTask,
)
from lazyllm.tools.writer.tools import (
    WriterContextTools,
    WriterDraftingTools,
    WriterPlanningTools,
    WriterQualityTools,
    WriterResourceTools,
)


def _workspace_root() -> Path:
    ctx = require_context()
    return Path(ctx.workspace_path) if ctx.workspace_path else Path('/tmp')


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


def profile_resources(writing_task_path: str, user_input: str) -> str:
    """产出 resource_profiles Artifact 文件。

    Args:
        writing_task_path: 上一步产出的 writing_task Artifact 文件绝对路径。
        user_input: 用户原始提示词，用于从中抽取飞书链接等 InputResource。

    Returns:
        resource_profiles Artifact 文件的绝对路径。
    """
    LOG.info(f'[writer-tool] profile_resources input writing_task_path={writing_task_path} user_input={user_input!r}')
    _read_artifact_file(writing_task_path)
    ctx = require_context()
    files_by_turn = ctx.params.get('history_files_per_turn') or {}
    all_files = [p for paths in files_by_turn.values() for p in paths]
    LOG.info(f'[writer-tool] profile_resources history_files_per_turn={files_by_turn} all_files_count={len(all_files)} all_files={all_files}')

    feishu_pattern = re.compile(r'https?://[A-Za-z0-9.\-]+\.feishu\.cn/\S+')
    seen_urls: set[str] = set()
    feishu_urls: list[str] = []
    for match in feishu_pattern.finditer(user_input or ''):
        url = match.group(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        feishu_urls.append(url)
    LOG.info(f'[writer-tool] profile_resources feishu_urls={feishu_urls} count={len(feishu_urls)}')

    input_resources: list[InputResource] = []
    for abs_path in all_files:
        input_resources.append(InputResource(
            resource_id=os.path.basename(abs_path), resource_type='file', uri=abs_path,
            title=os.path.basename(abs_path), mime_type=None, summary=None, meta={},
        ))
    for idx, url in enumerate(feishu_urls):
        input_resources.append(InputResource(
            resource_id=f'feishu_{idx}', resource_type='url', uri=url,
            title=None, mime_type=None, summary=None, meta={'provider': 'feishu', 'role': 'reference'},
        ))
    LOG.info(f'[writer-tool] profile_resources input_resources={[r.model_dump() for r in input_resources]}')
    result = WriterResourceTools(
        llm=AutoModel(model='llm'),
        artifact_store=str(_workspace_root()),
    ).profile_resources(task=writing_task_path, input_resources=input_resources)
    LOG.info(f'[writer-tool] profile_resources produced resource_profiles artifact counts={result["metadata"]["counts"]}')
    return result['artifact_path']


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
        llm=AutoModel(model='llm'),
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
        llm=AutoModel(model='llm'),
        artifact_store=str(_workspace_root()),
    ).generate_section_instructions(outline=outline_path, context=writing_context_path)
    LOG.info(f'[writer-tool] generate_section_instructions produced section_instructions artifact {result}')
    return result['artifact_path']


def generate_draft_section(
    writing_task_path: str,
    section_instructions_path: str,
    writing_context_path: str,
) -> str:
    """按已生成章节文件数量产出下一个 draft_section Artifact 文件。

    Args:
        writing_task_path: writing_task 文件路径。
        section_instructions_path: SectionInstructionList 文件路径。
        writing_context_path: writing_context 文件路径。

    Returns:
        draft_section 文件的绝对路径。全部章节生成完毕时返回空字符串。
    """
    LOG.info(
        '[writer-tool] generate_draft_section input '
        f'writing_task_path={writing_task_path} '
        f'section_instructions_path={section_instructions_path} '
        f'writing_context_path={writing_context_path}'
    )
    _read_artifact_file(writing_task_path)
    _read_artifact_file(writing_context_path)
    section_instructions = _read_artifact_file(section_instructions_path)
    if not isinstance(section_instructions, dict) or not isinstance(section_instructions.get('instructions'), list):
        raise TypeError('section_instructions_path must point to a SectionInstructionList artifact.')

    draft_sections_dir = _workspace_root() / 'draft_sections'
    draft_sections_dir.mkdir(parents=True, exist_ok=True)
    previous_paths = sorted(str(path) for path in draft_sections_dir.glob('draft_section_*.json'))
    next_index = len(previous_paths)
    instructions = section_instructions['instructions']
    if next_index >= len(instructions):
        LOG.info(
            '[writer-tool] generate_draft_section reached end '
            f'previous_count={len(previous_paths)} instruction_count={len(instructions)}'
        )
        return ''

    instruction = SectionInstruction.model_validate(instructions[next_index])
    previous_sections = [_read_artifact_file(path) for path in previous_paths]

    result = WriterDraftingTools(
        llm=AutoModel(model='llm'),
        artifact_store=str(draft_sections_dir),
    ).generate_draft_section(
        task=writing_task_path,
        section_instruction=instruction,
        context=writing_context_path,
        previous_sections=previous_sections,
    )
    produced_path = Path(result['artifact_path'])
    raw_id = instruction.outline_node_id or instruction.instruction_id or f'section-{next_index + 1}'
    safe_id = ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in raw_id)[:80]
    target_path = draft_sections_dir / f'draft_section_{next_index + 1:04d}_{safe_id}.json'
    if produced_path.resolve() != target_path.resolve():
        os.replace(produced_path, target_path)
    LOG.info(f'[writer-tool] generate_draft_section produced draft_section artifact path={target_path} raw_result={result}')
    return str(target_path)


def assemble_draft_document(
    draft_sections_anchor_path: str,
    writing_context_path: str,
    outline_path: str = '',
) -> str:
    """合并多个 draft_section 产出 draft_document Artifact 文件。

    Args:
        draft_sections_anchor_path: 任一 draft_section 文件路径，或 draft_sections 目录路径。
        writing_context_path: writing_context 文件路径。
        outline_path: outline 文件路径。

    Returns:
        draft_document 文件的绝对路径。
    """
    LOG.info(
        '[writer-tool] assemble_draft_document input '
        f'draft_sections_anchor_path={draft_sections_anchor_path} '
        f'writing_context_path={writing_context_path} '
        f'outline_path={outline_path}'
    )
    anchor = Path(draft_sections_anchor_path)
    draft_sections_dir = anchor if anchor.is_dir() else anchor.parent
    draft_sections_paths = sorted(str(path) for path in draft_sections_dir.glob('draft_section_*.json'))
    if not draft_sections_paths:
        raise ValueError('draft_sections_anchor_path must point to a generated draft_sections directory or file.')
    for path in draft_sections_paths:
        _read_artifact_file(path)
    _read_artifact_file(writing_context_path)
    outline_ref = outline_path or None
    if outline_ref:
        _read_artifact_file(outline_ref)

    result = WriterDraftingTools(
        llm=None,
        artifact_store=str(_workspace_root()),
    ).generate_draft_document(
        draft_sections=draft_sections_paths,
        context=writing_context_path,
        outline=outline_ref,
    )
    LOG.info(f'[writer-tool] assemble_draft_document produced draft_document artifact {result}')
    return result['artifact_path']


def update_writing_context(content_artifact_path: str, writing_context_path: str) -> str:
    """基于内容 artifact 更新 writing_context Artifact 文件。

    Args:
        content_artifact_path: 用于更新上下文的内容 artifact 文件路径。
        writing_context_path: writing_context 文件路径。

    Returns:
        writing_context 文件的绝对路径。
    """
    LOG.info(f'[writer-tool] update_writing_context input content_artifact_path={content_artifact_path} writing_context_path={writing_context_path}')
    _read_artifact_file(content_artifact_path)
    _read_artifact_file(writing_context_path)
    result = WriterContextTools(
        llm=None,
        artifact_store=str(_workspace_root()),
    ).update_writing_context(content_artifact=content_artifact_path, context=writing_context_path)
    LOG.info(f'[writer-tool] update_writing_context produced writing_context artifact {result}')
    return result['artifact_path']


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
    result = WriterQualityTools(
        llm=AutoModel(model='llm'),
        artifact_store=str(_workspace_root()),
    ).validate_draft_document(
        draft_document=draft_path,
        context=writing_context_path,
    )
    LOG.info(f'[writer-tool] check_consistency produced review_report artifact {result}')
    return result['artifact_path']


def generate_writing_output(
    draft_path: str, review_report_path: str, writing_context_path: str,
) -> Dict[str, str]:
    """产出两类 writing_output Artifact 文件。

    Args:
        draft_path: draft_document 文件路径。
        review_report_path: review_report 文件路径，用于确认审阅已完成。
        writing_context_path: writing_context 文件路径。

    Returns:
        两条绝对路径，需要分别调用 `save_artifact(content_type='file', key=<key>, value=<path>)` 进行落库。
    """
    LOG.info(
        '[writer-tool] generate_writing_output input '
        f'draft_path={draft_path} review_report_path={review_report_path} '
        f'writing_context_path={writing_context_path}'
    )
    _read_artifact_file(draft_path)
    _read_artifact_file(review_report_path)
    _read_artifact_file(writing_context_path)
    result = WriterDraftingTools(
        llm=None,
        artifact_store=str(_workspace_root()),
    ).generate_writing_output(
        draft=draft_path,
        context=writing_context_path,
    )
    returned: Dict[str, str] = {
        'writing_output': result['artifact_path'],
        'writing_output_md': result['output_file_path'],
    }
    LOG.info(
        f'[writer-tool] generate_writing_output produced {returned} raw_result={result}'
    )
    return returned
