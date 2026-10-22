import copy
import json
import unicodedata
from datetime import date
from pathlib import Path
from time import sleep
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit

import lazyllm
import httpx
from filelock import FileLock
from lazyllm import AutoModel, ThreadPoolExecutor
from lazyllm.tools.writer.tools.base import WriterToolBase
from pydantic import BaseModel, ConfigDict, Field, create_model

from lazymind.chat.engine.agent_runtime.budget import build_context_budget
from lazymind.common.token_estimation import estimate_tokens
from lazymind.config import config
from lazymind.model_config import _role_entry, load_model_config

from .contracts import MissingMaterials, validate_input
from .prompts.literature_review_prompt import (
    CANDIDATE_SELECTION_PROMPT,
    COVERAGE_PROMPT,
    INPUT_PROMPT,
    READING_NOTE_PROMPT,
    SEARCH_PLAN_PROMPT,
    SYNTHESIS_PROMPT,
)


class _SearchPlan(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    queries: dict[str, Annotated[int, Field(ge=1)]]
    year_from: int | None = None
    year_to: int | None = None
    paper_limit: int | None = Field(
        ge=1, description='The user\'s reference count target, retained even when exceeding it is allowed; null if unspecified.',
    )


class _ReadingNote(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    note: str = Field(min_length=1)
    citation: str


def _chunks(text: str, max_tokens: int) -> list[str]:
    chunks = []
    while text:
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if estimate_tokens(json.dumps(text[:middle], ensure_ascii=False)) <= max_tokens:
                low = middle
            else:
                high = middle - 1
        if low == 0:
            raise ValueError('研究要求和资料信息已占满模型的可用输入空间。')
        chunks.append(text[:low])
        text = text[low:]
    return chunks


def _read_note(source: dict, context: dict, input_tokens: int) -> dict:
    writer = WriterToolBase(llm=AutoModel(model='llm'))
    data = {**source, 'research': context, 'source_id': source['id'],
            'citation': source.get('citation', ''), 'text': ''}
    text = source['text']
    while True:
        overhead = estimate_tokens(INPUT_PROMPT.format(
            instruction=READING_NOTE_PROMPT, data=json.dumps(data, ensure_ascii=False),
        ))
        notes = []
        for chunk in _chunks(text, input_tokens - overhead):
            reading = writer._call_llm_structured(
                INPUT_PROMPT.format(instruction=READING_NOTE_PROMPT,
                                    data=json.dumps({**data, 'text': chunk}, ensure_ascii=False)),
                _ReadingNote,
            )
            notes.append(reading.note)
            if not data['citation']:
                data['citation'] = reading.citation
        if len(notes) == 1:
            source['citation'] = data['citation']
            return {**{key: value for key, value in source.items() if key != 'text'}, 'note': notes[0]}
        condensed = '\n\n'.join(notes)
        if estimate_tokens(condensed) >= estimate_tokens(text):
            raise ValueError('阅读笔记未能缩短输入内容，无法继续合并。')
        text = condensed


def _notes(sources: list[dict], context: dict) -> list[dict]:
    injected = lazyllm.globals['config'].get('dynamic_model_configs', {})
    role = injected.get('llm', {}).get('chat') or _role_entry(load_model_config().get('llm'))
    budget = build_context_budget(llm_config={'llm': role})
    with ThreadPoolExecutor() as executor:
        return list(executor.map(
            lambda source: _read_note(source, context, budget.effective_input_budget), sources,
        ))


def _identity(source: dict) -> set[tuple[str, str]]:
    metadata = source.get('metadata') or {}
    if source.get('kind') == 'knowledge_base':
        return {('knowledge_base', json.dumps(
            [metadata['kb_id'], metadata['doc_id']],
        ))}
    keys = set()
    title = unicodedata.normalize('NFKC', source['title']).casefold()
    keys.add(('title', ''.join(char for char in title if char.isalnum())))
    url = source.get('url', '')
    parts = urlsplit(url)
    if parts.netloc:
        keys.add(('url', parts.netloc.casefold() + unquote(parts.path).rstrip('/')
                  + ('?' + parts.query if parts.query else '')))
    doi = str(metadata.get('doi') or '').removeprefix('https://doi.org/').casefold()
    if parts.netloc.casefold() in ('doi.org', 'dx.doi.org'):
        doi = unquote(parts.path).lstrip('/').casefold()
    if doi:
        keys.add(('doi', doi))
    if metadata.get('doc_id'):
        keys.add((source.get('source', 'input'), str(metadata['doc_id'])))
    return {key for key in keys if key[1]}


def _provider(request: str):
    from lazymind.chat.service.component.tool_policy import select_search_provider
    from lazymind.chat.service.component.tool_registry import DEFAULT_TOOLS

    config = next(item for item in DEFAULT_TOOLS if item.name == 'academic_search')
    _, definition = select_search_provider(config, request)
    for provider in definition['tools']:
        if provider.__key_source__():
            return type(provider)(timeout=httpx.Timeout(None, connect=15))
    raise ValueError('所选学术检索服务缺少凭据，请在工具配置中填写。')


def _arxiv_request(call, *args, **kwargs):
    path = Path(config['agentic_workspace']) / 'academic-search' / 'arxiv.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    # arXiv 要求请求串行，间隔至少三秒；同一工作目录的进程共用文件锁。
    with FileLock(path):
        sleep(3)
        return call(*args, **kwargs)


def _search(provider, query: str, count: int, plan: _SearchPlan) -> list[dict]:
    if provider.source_name == 'sciverse':
        if count > 10:
            return provider.meta_search(
                query=query, page_size=count, include_content=False,
                year_from=plan.year_from, year_to=plan.year_to,
            )['items']
        return provider.search(
            query, topk=count, include_content=False,
            search_type='meta' if plan.year_from or plan.year_to else 'agentic',
            year_from=plan.year_from, year_to=plan.year_to,
        )
    if provider.source_name == 'arxiv':
        if plan.year_from or plan.year_to:
            start = plan.year_from or 1991
            end = plan.year_to or date.today().year
            query = f'({query}) AND submittedDate:[{start}01010000 TO {end}12312359]'
        return _arxiv_request(provider.search, query, max_results=count)
    raise ValueError(f'文献综述尚未接入检索服务：{provider.source_name}')


def _content(provider, source: dict) -> dict:
    if source.get('kind') == 'knowledge_base':
        from lazymind.chat.engine.tools.lazy_kb import KBToolkit

        metadata = source['metadata']
        content = KBToolkit().read_document(metadata['kb_id'], metadata['doc_id'])['content']
        if not content['text'].strip():
            raise MissingMaterials(f'知识库文档《{source["title"]}》没有可用正文。')
        source.update(text=content['text'], reading={
            'content_type': 'knowledge_base_document', 'truncated': content['truncated'],
        })
        return source
    offset = 0
    parts = []
    readings = []
    while True:
        if provider.source_name == 'arxiv':
            result = _arxiv_request(provider.get_content, source, offset=offset)
        else:
            result = provider.get_content(source, offset=offset)
        reading = result['extra']['content_read']
        if reading.get('pagination_error') or (offset and reading.get('fallback')):
            raise RuntimeError(f'论文《{source["title"]}》在位置 {offset} 的续页读取失败。')
        if not result['content'].strip():
            raise MissingMaterials(f'论文《{source["title"]}》未返回可用正文或摘要。')
        parts.append(result['content'])
        readings.append(reading)
        if not reading.get('more'):
            break
        next_offset = reading['next_offset']
        if next_offset <= offset:
            raise ValueError('论文内容服务返回了无效的后续位置。')
        offset = next_offset
    source.update(text=''.join(parts), reading=readings)
    return source


def _retrieve(provider, plan: _SearchPlan, sources: list[dict],
              seen: dict, used_ids: set[str], context: dict) -> list[dict]:
    candidates = []

    def register(source):
        keys = _identity(source)
        previous = next((seen[key] for key in keys if key in seen), None)
        if previous is not None:
            if source['kind'] == 'knowledge_base' and source['text'] not in previous['text']:
                previous['text'] += '\n\n' + source['text']
            metadata = previous.setdefault('metadata', {})
            for key, value in source['metadata'].items():
                metadata.setdefault(key, value)
            seen.update((key, previous) for key in keys)
            return
        prefix = 'KB' if source['kind'] == 'knowledge_base' else 'SRC'
        index = 1
        while f'{prefix}-{index:03d}' in used_ids:
            index += 1
        source['id'] = f'{prefix}-{index:03d}'
        used_ids.add(source['id'])
        seen.update((key, source) for key in keys)
        candidates.append(source)

    if provider.source_name == 'arxiv':
        batches = [_search(provider, query, count, plan) for query, count in plan.queries.items()]
    else:
        with ThreadPoolExecutor() as executor:
            batches = list(executor.map(
                lambda item: _search(provider, item[0], item[1], plan), plan.queries.items(),
            ))
    for batch in batches:
        for item in batch:
            if item.get('title', '').strip():
                register({**item, 'title': item['title'], 'url': item.get('url', ''),
                          'text': item.get('snippet', ''), 'source': provider.source_name,
                          'metadata': item.get('extra', {}),
                          'kind': 'paper', 'reading': '检索预览'})

    agentic = lazyllm.globals.get('agentic_config') or {}
    if (agentic.get('filters') or {}).get('kb_id'):
        from lazymind.chat.engine.tools.lazy_kb import KBToolkit

        toolkit = KBToolkit()
        for query, count in plan.queries.items():
            batch = toolkit.kb_search(query, k_max=count)['items']
            for item in batch:
                if item.get('text', '').strip():
                    register({**item, 'title': item.get('file_name') or item['docid'], 'url': '',
                              'text': item['text'], 'source': 'knowledge_base',
                              'metadata': {**item.get('metadata', {}),
                                           'kb_id': item['kb_id'], 'doc_id': item['docid'],
                                           'node_id': item['uid']},
                              'kind': 'knowledge_base', 'reading': '知识库节选'})
    if not candidates:
        return []
    by_id = {item['id']: item for item in candidates}
    selection_schema = create_model(
        'CandidateSelection', __base__=BaseModel,
        source_ids=(list[Literal[tuple(by_id)]], ...),
    )
    selection = WriterToolBase(llm=AutoModel(model='llm'))._call_llm_structured(
        INPUT_PROMPT.format(instruction=CANDIDATE_SELECTION_PROMPT, data=json.dumps(
            {'research': context,
             'paper_count': len(sources),
             'existing_titles': [item['title'] for item in sources],
             'candidates': candidates},
            ensure_ascii=False,
        )),
        selection_schema,
    )
    selected = [by_id[source_id] for source_id in dict.fromkeys(selection.source_ids)]
    if provider.source_name == 'arxiv':
        return [_content(provider, item) for item in selected]
    with ThreadPoolExecutor() as executor:
        return list(executor.map(lambda item: _content(provider, item), selected))


def _render(inputs: dict, notes: list[dict]) -> str:
    return WriterToolBase(llm=AutoModel(model='llm'))._call_llm_text(
        INPUT_PROMPT.format(instruction=SYNTHESIS_PROMPT, data=json.dumps(
            {'sources': [{key: note[key] for key in ('id', 'title', 'citation', 'note')} for note in notes],
             'research': {k: inputs.get(k) for k in ('topic', 'request', 'question')}},
            ensure_ascii=False,
        )),
    ).strip()


def run(inputs: dict) -> dict:
    inputs = validate_input('literature_review', inputs)
    sources = copy.deepcopy(inputs['papers'] or [])
    context = {key: inputs.get(key) for key in ('topic', 'request', 'question')}
    context['knowledge_base_ids'] = ((lazyllm.globals.get('agentic_config') or {}).get('filters') or {}).get('kb_id', [])
    writer = WriterToolBase(llm=AutoModel(model='llm'))
    notes = _notes(sources, context)
    plan = writer._call_llm_structured(
        INPUT_PROMPT.format(instruction=SEARCH_PLAN_PROMPT, data=json.dumps(
            {'research': context, 'previous_evidence': inputs.get('evidence'), 'papers': notes,
             'paper_count': len(sources), 'today': date.today().isoformat()}, ensure_ascii=False,
        )),
        _SearchPlan,
    )
    context['paper_limit'] = plan.paper_limit
    if plan.queries:
        provider = _provider(inputs.get('request', ''))
        seen = {key: source for source in sources for key in _identity(source)}
        used_ids = {paper['id'] for paper in sources}
        searched = set()
        for round_index in range(2):
            if plan.year_from and plan.year_to and plan.year_from > plan.year_to:
                raise ValueError('模型生成的检索年份范围无效。')
            added = _retrieve(provider, plan, sources, seen, used_ids, context)
            sources.extend(added)
            notes.extend(_notes(added, context))
            searched.update(plan.queries)
            if round_index == 1:
                break
            plan = writer._call_llm_structured(
                INPUT_PROMPT.format(instruction=COVERAGE_PROMPT, data=json.dumps(
                    {'research': context, 'previous_evidence': inputs.get('evidence'), 'sources': notes,
                     'paper_count': len(sources),
                     'searched_queries': sorted(searched), 'provider': provider.source_name,
                     'today': date.today().isoformat()}, ensure_ascii=False,
                )),
                _SearchPlan,
            )
            plan.queries = {query: count for query, count in plan.queries.items() if query not in searched}
            if not plan.queries:
                break
    if not sources:
        raise MissingMaterials('没有可用于综述的论文或知识库材料，请调整研究范围或提供论文。')
    evidence = _render(inputs, notes)
    return {'evidence': evidence, 'papers': sources, 'is_demo': False}
