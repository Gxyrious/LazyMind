"""Writer tools for long-form writing plugin steps."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from lazyllm import AutoModel
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
from lazyllm.tools.writer.utils import save_artifact_json

from lazymind.chat.engine.subagent.context import require_context


def _workspace_root() -> Path:
    ctx = require_context()
    return Path(ctx.workspace_path) if ctx.workspace_path else Path('/tmp')


def _read_artifact_file(path: str) -> Any:
    """Read an artifact file from the workspace, unwrapping the `data` field when present."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, 'r', encoding='utf-8') as fh:
        raw = json.load(fh)
    if isinstance(raw, dict) and 'data' in raw:
        raw = raw['data']
    return raw


class WriterToolGroup:
    """Tools for building writing tasks, outlines, drafts, reviews, and final reports."""

    __public_apis__ = [
        'build_writing_task',
        'profile_resources',
        'create_writing_context',
        'generate_outline',
        'generate_section_instructions',
        'generate_draft_section',
        'assemble_draft_document',
        'update_writing_context',
        'check_consistency',
        'generate_writing_output',
    ]

    def __key_source__(self) -> bool:
        try:
            require_context()
            return True
        except Exception:
            return False

    def build_writing_task(self, query: str) -> str:
        """Build a WritingTask and emit the writing_task artifact file.

        Args:
            query: The user's original writing request.

        Returns:
            Absolute path of the writing_task artifact file.
        """
        task = WritingTask(query=query, task_type='write')  # TODO: use LLM for richer construction
        path = _workspace_root() / 'writing_task.json'
        save_artifact_json(task, str(path), created_by='build_writing_task')
        return str(path)

    def profile_resources(self, writing_task_path: str, user_input: str) -> str:
        """Emit the resource_profiles artifact file.

        Args:
            writing_task_path: Absolute path of the writing_task artifact from the previous step.
            user_input: The user's original prompt, used to extract Feishu links as InputResource.

        Returns:
            Absolute path of the resource_profiles artifact file.
        """
        _read_artifact_file(writing_task_path)
        ctx = require_context()
        files_by_turn = ctx.params.get('history_files_per_turn') or {}
        all_files = [p for paths in files_by_turn.values() for p in paths]

        feishu_pattern = re.compile(r'https?://[A-Za-z0-9.\-]+\.feishu\.cn/\S+')
        seen_urls: set[str] = set()
        feishu_urls: list[str] = []
        for match in feishu_pattern.finditer(user_input or ''):
            url = match.group(0)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            feishu_urls.append(url)

        input_resources: list[InputResource] = []
        for abs_path in all_files:
            input_resources.append(InputResource(
                resource_id=os.path.basename(abs_path), resource_type='file', uri=abs_path,
                title=os.path.basename(abs_path), mime_type=None, summary=None, meta={},
            ))
        for idx, url in enumerate(feishu_urls):
            input_resources.append(InputResource(
                resource_id=f'feishu_{idx}', resource_type='url', uri=url,
                title=None, mime_type=None, summary=None, meta={'provider': 'feishu', 'role': 'background'},
            ))
        result = WriterResourceTools(
            llm=AutoModel(model='llm'),
            artifact_store=str(_workspace_root()),
        ).profile_resources(task=writing_task_path, input_resources=input_resources)
        return result['artifact_path']

    def create_writing_context(self, writing_task_path: str, resource_profiles_path: str) -> str:
        """Emit the writing_context artifact file.

        Args:
            writing_task_path: Absolute path of the writing_task artifact.
            resource_profiles_path: Absolute path of the resource_profiles artifact.

        Returns:
            Absolute path of the writing_context artifact file.
        """
        _read_artifact_file(writing_task_path)
        _read_artifact_file(resource_profiles_path)
        result = WriterContextTools(
            llm=None,
            artifact_store=str(_workspace_root()),
        ).create_writing_context(task=writing_task_path, resource_profiles=resource_profiles_path)
        return result['artifact_path']

    def generate_outline(self, writing_task_path: str, writing_context_path: str) -> str:
        """Emit the outline artifact file.

        Args:
            writing_task_path: Absolute path of the writing_task artifact.
            writing_context_path: Absolute path of the writing_context artifact.

        Returns:
            Absolute path of the outline artifact file.
        """
        _read_artifact_file(writing_task_path)
        _read_artifact_file(writing_context_path)
        result = WriterPlanningTools(
            llm=AutoModel(model='llm'),
            artifact_store=str(_workspace_root()),
        ).generate_outline(task=writing_task_path, context=writing_context_path)
        return result['artifact_path']

    def generate_section_instructions(
        self,
        outline_path: str,
        writing_context_path: str,
        review_report_path: str = '',
    ) -> str:
        """Emit the section_instructions artifact file containing the full SectionInstructionList.

        Args:
            outline_path: Absolute path of the outline artifact.
            writing_context_path: Absolute path of the writing_context artifact.
            review_report_path: Absolute path of the review_report artifact.

        Returns:
            Absolute path of the section_instructions artifact file.
        """
        _read_artifact_file(outline_path)
        _read_artifact_file(writing_context_path)
        execution_results: Any = None
        if review_report_path:
            execution_results = _read_artifact_file(review_report_path)
        result = WriterPlanningTools(
            llm=AutoModel(model='llm'),
            artifact_store=str(_workspace_root()),
        ).generate_section_instructions(
            outline=outline_path,
            context=writing_context_path,
            execution_results=execution_results,
        )
        return result['artifact_path']

    def generate_draft_section(
        self,
        writing_task_path: str,
        section_instructions_path: str,
        writing_context_path: str,
    ) -> str:
        """Emit the next draft_section artifact file.

        Args:
            writing_task_path: Path to the writing_task file.
            section_instructions_path: Path to the SectionInstructionList file.
            writing_context_path: Path to the writing_context file.

        Returns:
            Absolute path of the draft_section file. Returns an empty string once
            every section has been generated.
        """
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
        return result['artifact_path']

    def assemble_draft_document(
        self,
        draft_sections_anchor_path: str,
        writing_context_path: str,
        outline_path: str = '',
    ) -> str:
        """Merge multiple draft_sections into the draft_document artifact file.

        Args:
            draft_sections_anchor_path: Any draft_section file path, or the draft_sections directory path.
            writing_context_path: Path to the writing_context file.
            outline_path: Path to the outline file.

        Returns:
            Absolute path of the draft_document file.
        """
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
        return result['artifact_path']

    def update_writing_context(self, content_artifact_path: str, writing_context_path: str) -> str:
        """Update the writing_context artifact based on a content artifact.

        Args:
            content_artifact_path: Path to the content artifact used to update the context.
            writing_context_path: Path to the writing_context file.

        Returns:
            Absolute path of the writing_context file.
        """
        _read_artifact_file(content_artifact_path)
        _read_artifact_file(writing_context_path)
        result = WriterContextTools(
            llm=None,
            artifact_store=str(_workspace_root()),
        ).update_writing_context(artifacts=content_artifact_path, context=writing_context_path)
        return result['artifact_path']

    def check_consistency(self, draft_path: str, writing_context_path: str) -> Dict[str, str]:
        """Emit the review_report artifact file and return a review summary.

        Args:
            draft_path: Path to the draft_document file.
            writing_context_path: Path to the writing_context file.

        Returns:
            Two fields; call `save_artifact(content_type='file', key='review_report')`
            and `save_artifact(content_type='text', key='review_summary')` to persist them.
        """
        _read_artifact_file(draft_path)
        _read_artifact_file(writing_context_path)
        result = WriterQualityTools(
            llm=AutoModel(model='llm'),
            artifact_store=str(_workspace_root()),
        ).validate_draft_document(
            draft_document=draft_path,
            context=writing_context_path,
        )
        return {
            'review_report': result['artifact_path'],
            'review_summary': result['summary'],
        }

    def generate_writing_output(
        self,
        draft_path: str,
        review_report_path: str,
        writing_context_path: str,
    ) -> Dict[str, str]:
        """Emit two writing_output artifact files.

        Args:
            draft_path: Path to the draft_document file.
            review_report_path: Path to the review_report file.
            writing_context_path: Path to the writing_context file.

        Returns:
            Two absolute paths; call `save_artifact(content_type='file', key=<key>, value=<path>)` for each.
        """
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
        return {
            'writing_output': result['artifact_path'],
            'writing_output_md': result['output_file_path'],
        }
