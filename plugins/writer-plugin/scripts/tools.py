"""Writer-plugin mock tools — the 7 doc-named Writer Tools, key-in / key-out.

Each tool is LLM-callable by its doc name (profile_resources, create_writing_context,
generate_outline, generate_section_instructions, generate_draft_section,
check_consistency, generate_writing_output). The LLM passes only artifact KEYS and
receives a short confirmation — it never relays structured payload, which removes the
re-serialization/restructuring failure mode entirely. Each tool reads its inputs from
the artifact store itself and writes its output itself.

Doc tools that chain (profile_resources -> create_writing_context, etc.) pass
intermediates by key; those intermediates are stored as plain artifacts (no slot) and
read session-wide. The per-section loop lives inside generate_draft_section because the
instructions list is kept out of the LLM's view (it only sees a key).

All return shapes match docs/WriterAgent-Design.md data models.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List

import lazyllm
from lazymind.chat.engine.subagent import tools as _sub
from lazymind.chat.engine.subagent.context import require_context


# ---------------------------------------------------------------------------
# artifact I/O — the only place aware of storage shape
# ---------------------------------------------------------------------------

def _read(key: str) -> Any:
    """Read the latest value of an artifact by key, session-wide.

    Covers two scopes: prior completed steps' tasks AND the current task (so tools
    chained within one step — e.g. profile_resources then create_writing_context in
    build_context — can read each other's just-saved artifacts). json artifacts are
    stored as {'data': <model>}; unwrap once. A missing artifact fails naturally.
    """
    ctx = require_context()
    sid = ''
    try:
        sid = (lazyllm.globals.get('agentic_config') or {}).get('plugin_session_id', '') or ''
    except Exception:
        sid = ''
    task_ids = [ctx.task_id]
    if sid:
        for s in ctx.db.load_plugin_session_steps(sid):
            tid = s.get('task_id')
            if tid and tid not in task_ids:
                task_ids.append(tid)
    rows = ctx.db.load_artifacts_for_tasks(task_ids)
    # load_artifacts_for_tasks only reads DB; artifacts saved earlier in the *current*
    # task are also in the local buffer, so merge those in (same shape).
    for a in (ctx.local_artifacts(keys=[key]) or []):
        rows.append(a)
    matching = [r for r in rows if r.get('artifact_key') == key]
    latest = max(matching, key=lambda r: r.get('seq', 0))
    v = latest.get('value') or {}
    if isinstance(v, dict) and 'data' in v:
        return v['data']
    return v


def _save(key: str, model: Any) -> str:
    """Persist a value under key as a json artifact; return a short confirmation."""
    _sub.save_artifact(key=key, value=model, content_type='json')
    return f"saved artifact '{key}'"


def _new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:10]}'


# ---------------------------------------------------------------------------
# mock compute helpers (pure; doc-shaped; consume inputs → differentiated output)
# ---------------------------------------------------------------------------

def _profile_resources(query: str) -> List[Dict[str, Any]]:
    # No input materials in this bringup flow; the honest result is an empty profile
    # list. create_writing_context handles [] (resource_count=0).
    return []


def _create_writing_context(query: str, resource_profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    topic = (query or '').strip() or '给定主题'
    for p in ('请写一篇关于', '请写一份关于', '帮我写一篇关于', '写一篇关于', '请就', '请写'):
        if topic.startswith(p):
            topic = topic[len(p):]
            break
    topic = topic.split('的')[0].split('，')[0].strip('「」“”"') or topic
    return {
        'context_id': _new_id('ctx'), 'doc_id': None,
        'document_summary': {
            'summary': f'(mock) 本文围绕「{topic}」展开，覆盖核心概念、主要方法与挑战。',
            'key_points': [f'{topic}基本概念', '主要方法', '主要挑战'],
            'structure_summary': '背景 → 概念 → 方法 → 挑战 → 总结',
        },
        'block_summaries': [],
        'facts': [{'fact_id': 'f1', 'key': '主题', 'value': topic,
                   'source': [], 'applies_to_block_ids': [], 'locked': False}],
        'style_profile': None, 'relation_graph': None,
        'meta': {'mock': True, 'topic': topic, 'resource_count': len(resource_profiles)},
    }


def _generate_outline(writing_context: Dict[str, Any]) -> Dict[str, Any]:
    topic = (writing_context.get('meta') or {}).get('topic') or '给定主题'
    return {
        'outline_id': _new_id('ol'), 'title': topic,
        'nodes': [
            {'node_id': 'n1', 'title': '引言', 'level': 1,
             'instruction': f'交代{topic}的研究动机', 'constraints': {}, 'children': [], 'meta': {}},
            {'node_id': 'n2', 'title': '基本概念', 'level': 1,
             'instruction': f'定义{topic}的核心概念', 'constraints': {},
             'children': [{'node_id': 'n2-1', 'title': '核心定义', 'level': 2,
                           'instruction': '形式化定义与术语', 'constraints': {}, 'children': [], 'meta': {}}],
             'meta': {}},
            {'node_id': 'n3', 'title': '主要方法与挑战', 'level': 1,
             'instruction': f'梳理{topic}的方法与挑战', 'constraints': {}, 'children': [], 'meta': {}},
        ],
        'meta': {'mock': True},
    }


def _generate_section_instructions(outline: Dict[str, Any],
                                   writing_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    topic = (writing_context.get('meta') or {}).get('topic') or '给定主题'
    out = []
    top = [n for n in (outline.get('nodes') or []) if (n.get('level') or 1) == 1]
    for i, node in enumerate(top):
        title = node.get('title') or f'第{i+1}章'
        out.append({
            'instruction_id': _new_id('instr'),
            'outline_node_id': node.get('node_id') or f'n{i+1}',
            'section_title': title,
            'section_goal': node.get('instruction') or f'阐述{title}',
            'required_points': [f'{title}要点一', f'{title}要点二', f'与{topic}的关联'],
            'source_refs': [], 'fact_constraint': [], 'style_constraints': ['正式'],
            'relation_constraints': [], 'visual_needs': [], 'expected_blocks': [f'b-{i+1}'],
            'pending_subtasks': [], 'revision_notes': [],
            'meta': {'mock': True, 'topic': topic, 'order': i + 1},
        })
    return out


def _generate_one_draft_section(instruction: Dict[str, Any],
                                writing_context: Dict[str, Any]) -> Dict[str, Any]:
    topic = (writing_context.get('meta') or {}).get('topic') or '给定主题'
    title = instruction.get('section_title') or '章节'
    goal = instruction.get('section_goal') or ''
    points = instruction.get('required_points') or []
    node_id = instruction.get('outline_node_id') or 'n?'
    content = (f'## {title}\n\n(mock) 本章围绕「{title}」展开，目标：{goal}。\n\n'
               f'要点：{"；".join(points) if points else "（无）"}\n\n'
               f'(mock) 围绕「{title}」与主题「{topic}」的占位正文。')
    return {
        'section_id': _new_id('sec'), 'outline_node_id': node_id, 'title': title,
        'instruction_id': instruction.get('instruction_id') or _new_id('instr'),
        'sub_sections': [],
        'blocks': [{'block_id': _new_id('b'), 'outline_node_id': node_id, 'section_id': None,
                    'heading': title, 'content': content, 'subtasks': [], 'meta': {'mock': True}}],
        'subtasks': [], 'meta': {'mock': True, 'topic': topic},
    }


def _check_consistency(draft: Dict[str, Any],
                       writing_context: Dict[str, Any]) -> Dict[str, Any]:
    ids = [s.get('section_id') or s.get('title')
           for s in (draft.get('sections') or []) if isinstance(s, dict)]
    issues = []
    if ids:
        issues.append({'severity': 'medium', 'category': 'coverage', 'location': ids[0],
                       'description': '(mock) 首章展开不足。', 'suggestion': '补充背景。'})
    if len(ids) >= 2:
        issues.append({'severity': 'low', 'category': 'style', 'location': ids[1],
                       'description': '(mock) 术语一致性。', 'suggestion': '统一术语。'})
    if len(ids) >= 3:
        issues.append({'severity': 'medium', 'category': 'evidence', 'location': ids[2],
                       'description': '(mock) 方法章节缺示例。', 'suggestion': '补示例。'})
    return {
        'is_passed': not issues, 'score': max(60, 90 - 8 * len(issues)),
        'summary': f'(mock) 共 {len(ids)} 章；' + ('一致。' if not issues else f'{len(issues)} 处可改。'),
        'issues': issues, 'meta': {'mock': True},
    }


def _generate_writing_output(draft: Dict[str, Any], review_report: Dict[str, Any],
                             writing_context: Dict[str, Any]) -> Dict[str, Any]:
    topic = (writing_context.get('meta') or {}).get('topic') or '给定主题'
    title = draft.get('title') or topic
    parts = [f'# {title}\n']
    for s in (draft.get('sections') or []):
        parts.append(f'\n## {s.get("title", "章节")}\n')
        for b in (s.get('blocks') or []):
            if b.get('content'):
                parts.append(b['content'] + '\n')
    return {
        'output_id': _new_id('out'), 'title': title, 'content': '\n'.join(parts),
        'output_format': 'markdown', 'references': [], 'media_assets': [],
        'meta': {'mock': True, 'topic': topic,
                 'review_issues_seen': len(review_report.get('issues') or [])},
    }


# ---------------------------------------------------------------------------
# doc-named Writer Tools (LLM-callable; key in / confirmation out)
# ---------------------------------------------------------------------------

def profile_resources(query: str) -> str:
    """识别输入资源的写作角色，产出 resource_profiles artifact。

    Args:
        query: 用户原始写作请求（来自 user_input）。
    """
    return _save('resource_profiles', _profile_resources(query))


def create_writing_context(resource_profiles_key: str, query: str) -> str:
    """基于 resource_profiles 初始化 WritingContext，产出 writing_context artifact。

    Args:
        resource_profiles_key: profile_resources 产出的 artifact key。
        query: 用户原始写作请求（用于主题解析）。
    """
    profiles = _read(resource_profiles_key)
    return _save('writing_context', _create_writing_context(query, profiles))


def generate_outline(writing_context_key: str) -> str:
    """基于 writing_context 生成大纲，产出 outline artifact。

    Args:
        writing_context_key: writing_context 的 artifact key。
    """
    wc = _read(writing_context_key)
    return _save('outline', _generate_outline(wc))


def generate_section_instructions(outline_key: str, writing_context_key: str) -> str:
    """基于大纲为每个顶层章节生成 SectionInstruction，产出 section_instructions artifact。

    Args:
        outline_key: outline 的 artifact key。
        writing_context_key: writing_context 的 artifact key。
    """
    outline = _read(outline_key)
    wc = _read(writing_context_key)
    return _save('section_instructions', _generate_section_instructions(outline, wc))


def generate_draft_section(section_instructions_key: str, writing_context_key: str) -> str:
    """按 section_instructions 逐章生成草稿：每章存为 draft_section（list），并装配 draft。

    说明：instructions 列表对 LLM 不可见（只看到 key），因此逐章循环在本工具内部完成。

    Args:
        section_instructions_key: generate_section_instructions 产出的 artifact key。
        writing_context_key: writing_context 的 artifact key。
    """
    instructions = _read(section_instructions_key) or []
    wc = _read(writing_context_key)
    sections = []
    for instr in instructions:
        sec = _generate_one_draft_section(instr, wc)
        sections.append(sec)
        _save('draft_section', sec)
    draft = {
        'draft_id': _new_id('dft'),
        'title': (wc.get('meta') or {}).get('topic') or 'Draft',
        'sections': sections,
        'meta': {'mock': True, 'section_count': len(sections)},
    }
    return _save('draft', draft)


def check_consistency(draft_key: str, writing_context_key: str) -> str:
    """对 draft 做一致性/质量审阅，产出 review_report artifact。

    Args:
        draft_key: draft 的 artifact key。
        writing_context_key: writing_context 的 artifact key。
    """
    draft = _read(draft_key)
    wc = _read(writing_context_key)
    return _save('review_report', _check_consistency(draft, wc))


def generate_writing_output(draft_key: str, review_report_key: str,
                            writing_context_key: str) -> str:
    """基于 draft 与 review 产出最终成稿，产出 final_report artifact。

    Args:
        draft_key: draft 的 artifact key。
        review_report_key: review_report 的 artifact key。
        writing_context_key: writing_context 的 artifact key。
    """
    draft = _read(draft_key)
    report = _read(review_report_key)
    wc = _read(writing_context_key)
    return _save('final_report', _generate_writing_output(draft, report, wc))
