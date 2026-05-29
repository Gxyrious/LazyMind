from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterator
from fastapi import APIRouter, HTTPException
from evo.service.core import store as _store
from evo.service.threads.model import (
    TraceCompareResponse,
    TraceContext,
    TraceDetailResponse,
    TraceSummary,
)
from evo.service.threads.workspace import ThreadWorkspace
from lazyllm.tracing.consume import get_single_trace
from lazyllm.tracing.datamodel.structured import ExecutionStep, StructuredTrace
from lazyllm.tracing.semantics import SemanticType


def build_results_router(*, base_dir: Path, store: _store.FsStateStore) -> APIRouter:
    router = APIRouter(prefix='/v1/evo/threads/{thread_id}/results', tags=['thread-results'])

    @router.get('/datasets')
    def datasets(thread_id: str) -> list[dict]:
        ws = _ws(base_dir, thread_id)
        ids = _dataset_ids(base_dir, ws, store, thread_id)
        return [{'dataset_id': i,
                 'path': str(p := Path(base_dir) / 'datasets' / i / 'eval_data.json'),
                 'exists': p.is_file(),
                 'case_count': len((_json(p) or {}).get('cases') or []),
                 'kb_id': (_json(p) or {}).get('kb_id')} for i in ids]

    @router.get('/eval-reports')
    def eval_reports(thread_id: str) -> list[dict]:
        ws = _ws(base_dir, thread_id)
        out = []
        for row in _store.list_flow_tasks_by_thread(store, 'eval', thread_id):
            eval_id = ((row.get('payload') or {}).get('eval_id') or '').strip()
            if eval_id and (path := ws.eval_path(eval_id)).is_file():
                out.append(_eval_report(path, row))
        if not out:
            for eval_id in ws.load_artifacts().get('eval_ids') or []:
                if (path := ws.eval_path(eval_id)).is_file():
                    out.append(_eval_report(path))
        return out

    @router.get('/analysis-reports')
    def analysis_reports(thread_id: str) -> list[dict]:
        ws = _ws(base_dir, thread_id)
        out = []
        for row in _store.list_flow_tasks_by_thread(store, 'run', thread_id):
            if not (rid := (row.get('payload') or {}).get('report_id')):
                continue
            jp = _first(ws.dir / 'outputs' / 'reports' / f'{rid}.json', Path(base_dir)
                        / 'work' / 'reports' / f'{rid}.json', Path(base_dir) / 'reports' / f'{rid}.json')
            mp = _first(ws.dir / 'outputs' / 'reports' / f'{rid}.md', Path(base_dir)
                        / 'work' / 'reports' / f'{rid}.md', Path(base_dir) / 'reports' / f'{rid}.md')
            data = _json(jp)
            out.append({'run_id': row['id'], 'report_id': rid, 'json_path': str(jp),
                       'md_path': str(mp), 'json': data, 'markdown': _text(mp), '_empty': _empty_analysis(data)})
        if any(not item['_empty'] for item in out):
            out = [item for item in out if not item['_empty']]
        for item in out:
            item.pop('_empty', None)
        return out

    @router.get('/diffs')
    def diffs(thread_id: str) -> list[dict]:
        ws = _ws(base_dir, thread_id)
        rows = sorted(_store.list_flow_tasks_by_thread(store, 'apply', thread_id),
                      key=lambda r: r.get('created_at') or 0, reverse=True)
        out = []
        for idx, row in enumerate(rows):
            preview = _preview(base_dir, ws, row['id'])
            data = _json(preview) or {}
            result = ((row.get('payload') or {}).get('result') or {})
            out.append({'apply_id': row['id'],
                        'status': row.get('status'),
                        'created_at': row.get('created_at'),
                        'updated_at': row.get('updated_at'),
                        'terminal_at': row.get('terminal_at'),
                        'final_commit': row.get('final_commit') or result.get('final_commit'),
                        'is_latest': idx == 0,
                        'preview_path': str(preview) if preview.is_file() else None,
                        'preview': data or None,
                        'files': _files(data)})
        return out

    @router.get('/abtests')
    def abtests(thread_id: str) -> list[dict]:
        ws = _ws(base_dir, thread_id)
        return [
            {
                'abtest_id': i,
                'summary': _json(
                    d
                    / 'summary.json'),
                'decision': _json(
                    d
                    / 'decision.json'),
                'markdown': _text(
                    d
                    / 'summary.md')} for i in ws.load_artifacts().get('abtest_ids') or [] for d in [
                ws.dir
                / 'abtests'
                / i]]

    @router.get('/traces/{trace_id}')
    def trace_detail(thread_id: str, trace_id: str) -> dict:
        _ws(base_dir, thread_id)
        return asdict(_build_trace_detail(trace_id))

    @router.get('/traces-compare')
    def trace_compare(thread_id: str, a: str, b: str) -> dict:
        _ws(base_dir, thread_id)
        return asdict(_build_trace_compare(a, b))

    return router


def _ws(base_dir: Path, thread_id: str) -> ThreadWorkspace:
    ws = ThreadWorkspace(base_dir, thread_id, create=False)
    if not ws.thread_meta_path.exists():
        raise HTTPException(404, f'thread {thread_id} not found')
    return ws


def _json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return None


def _eval_report(path: Path, row: dict | None = None) -> dict:
    data = _json(path) or {}
    summary = _case_details_summary(data.get('case_details') or [])
    return {
        'eval_id': path.stem,
        'task_id': (row or {}).get('id'),
        'path': str(path),
        'report_id': data.get('report_id'),
        'total_cases': data.get('total_cases') or summary['total_count'],
        'metrics': summary['averages'],
        'case_details_summary': summary,
    }


def _build_trace_detail(trace_id: str) -> TraceDetailResponse:
    trace = None
    if trace_id:
        try:
            trace = get_single_trace(trace_id)
        except Exception:
            trace = None
    trace_status = 'success' if trace else 'trace_missing'
    return TraceDetailResponse(
        trace_id=trace_id,
        trace_status=trace_status,
        context=_trace_context(trace),
        query=_trace_query(trace),
        summary=_trace_summary(trace, trace_status),
        trace=trace,
    )


def _build_trace_compare(a: str, b: str) -> TraceCompareResponse:
    side_a = _build_trace_detail(a)
    side_b = _build_trace_detail(b)
    return TraceCompareResponse(
        case_id=side_a.context.case_id or side_b.context.case_id,
        query=side_a.query or side_b.query,
        a=side_a,
        b=side_b,
    )


def _trace_context(trace: StructuredTrace | None) -> TraceContext:
    context = trace.metadata.metadata if trace and isinstance(trace.metadata.metadata, dict) else {}
    return TraceContext(
        scene=str(context.get('scene') or ''),
        report_id=str(context.get('report_id') or ''),
        dataset_id=str(context.get('dataset_id') or ''),
        case_id=str(context.get('case_id') or ''),
        knowledge_base_id=str(context.get('knowledge_base_id') or ''),
        algorithm_version=str(context.get('algorithm_version') or ''),
    )


def _trace_query(trace: StructuredTrace | None) -> str:
    raw_data = trace.execution_tree.raw_data if trace and trace.execution_tree else None
    inputs = raw_data.input if raw_data else None
    if isinstance(inputs, str):
        try:
            inputs = json.loads(inputs)
        except json.JSONDecodeError:
            return inputs
    if isinstance(inputs, dict):
        args = inputs.get('args')
        if isinstance(args, list) and args and isinstance(args[0], str):
            return args[0]
    return ''


def _trace_summary(trace: StructuredTrace | None, trace_status: str) -> TraceSummary:
    tree = trace.execution_tree if trace else None
    metadata = trace.metadata if trace else None
    nodes = list(_walk_tree(tree)) if tree else []
    status = str((metadata.status if metadata else '') or (tree.status if tree else '') or trace_status)
    return TraceSummary(
        status=status,
        latency_ms=metadata.latency_ms if metadata else None,
        round_count=_agent_round_count(tree),
        tool_call_count=_tool_call_count(nodes),
        retrieval_count=sum(1 for node in nodes if node.semantic_type == SemanticType.RETRIEVER),
        rerank_count=sum(1 for node in nodes if node.semantic_type == SemanticType.RERANK),
    )


def _walk_tree(node: ExecutionStep | None) -> Iterator[ExecutionStep]:
    if node is None:
        return
    yield node
    for child in node.children:
        yield from _walk_tree(child)


def _agent_round_count(root: ExecutionStep | None) -> int:
    def visit(node: ExecutionStep, in_agent: bool) -> int:
        semantic_type = node.semantic_type
        in_agent = in_agent or semantic_type == SemanticType.AGENT
        if in_agent and semantic_type in (SemanticType.TOOL, SemanticType.RETRIEVER, SemanticType.RERANK):
            return 0
        return int(in_agent and semantic_type == SemanticType.LLM) + sum(visit(child, in_agent) for child in node.children)

    return visit(root, False) if root else 0


def _tool_call_count(nodes: list[ExecutionStep]) -> int:
    count = 0
    for node in nodes:
        if node.semantic_type != SemanticType.TOOL:
            continue
        raw_input = node.raw_data.input
        args = raw_input.get('args') if isinstance(raw_input, dict) else None
        tool_calls = args[0] if isinstance(args, list) and args else None
        count += len(tool_calls) if isinstance(tool_calls, list) else 1
    return count


def _case_details_summary(cases: list[dict]) -> dict:
    buckets: dict[int, list[dict]] = {}
    for case in cases:
        buckets.setdefault(int(case.get('question_type') or 1), []).append(case)
    return {
        'total_count': len(cases),
        'averages': _averages(cases),
        'question_types': [
            {
                'question_type': key,
                'count': len(items),
                'averages': _averages(items),
            }
            for key, items in sorted(buckets.items())
        ],
    }


def _averages(cases: list[dict]) -> dict[str, float]:
    metrics = ('answer_correctness', 'faithfulness', 'context_recall', 'doc_recall')
    return {
        key: round(sum(float(case.get(key) or 0) for case in cases) / len(cases), 4) if cases else 0.0
        for key in metrics
    }


def _empty_analysis(data: dict | None) -> bool:
    if not data:
        return True
    meta = data.get('metadata') or {}
    return (
        int(meta.get('total_cases') or 0) == 0
        and not data.get('actions')
        and not data.get('hypotheses')
        and not data.get('findings')
    )


def _first(*paths: Path) -> Path:
    return next((p for p in paths if p.is_file()), paths[0])


def _dataset_ids(base_dir: Path, ws: ThreadWorkspace, store: _store.FsStateStore, thread_id: str) -> list[str]:
    ids: list[str] = []

    def add(dataset_id: str | None) -> None:
        path = Path(base_dir) / 'datasets' / str(dataset_id) / 'eval_data.json' if dataset_id else None
        if dataset_id and dataset_id not in ids and path and path.is_file():
            ids.append(dataset_id)

    for dataset_id in ws.load_artifacts().get('dataset_ids') or []:
        add(str(dataset_id))
    for row in _store.list_flow_tasks_by_thread(store, 'dataset_gen', thread_id):
        add((row.get('payload') or {}).get('eval_name'))
    for row in _store.list_flow_tasks_by_thread(store, 'eval', thread_id):
        add((row.get('payload') or {}).get('dataset_id'))
    return ids


def _preview(base_dir: Path, ws: ThreadWorkspace, apply_id: str) -> Path:
    rels = [Path('applies') / apply_id / 'preview' / apply_id / 'index.json',
            Path('applies') / apply_id / 'preview' / 'index.json']
    return _first(*(p for r in rels for p in (ws.dir / 'outputs' / r, Path(base_dir) / 'work' / r)))


def _files(preview: dict) -> list[dict]:
    out = []
    for item in preview.get('files') or []:
        if isinstance(item, dict):
            path = Path(str(item.get('diff_path') or ''))
            out.append({'path': item.get('path'),
                        'change_kind': item.get('change_kind'),
                        'additions': item.get('additions'),
                        'deletions': item.get('deletions'),
                        'diff_path': str(path) if str(path) else None,
                        'filename': path.name or None,
                        'content': _text(path) if path.is_file() else None})
    return out
