import copy
import os

import pytest

from lazymind.document_tools.paper import api, contracts, workflow


TOPIC = '时间同步系统的组合学习（形式化方法与时间自动机的组合式主动学习）'


@pytest.fixture
def paper():
    return {
        'id': 'SRC-001',
        'title': 'A Detailed Account of Compositional Automata Learning Through Alphabet Refinement',
        'text': 'Active automata learning infers automaton models of systems from behavioral observations, '
                'a technique successfully applied to a wide range of domains. Compositional approaches '
                'have recently emerged to address scalability to concurrent systems.',
        'citation': 'Henry L, Mousavi M R, Neele T, et al. A detailed account of compositional automata '
                    'learning through alphabet refinement[EB/OL]. arXiv:2504.16624v3, 2025.',
        'metadata': {'arxiv_id': '2504.16624v3', 'year': 2025},
        'user_annotations': {'focus': '同步并行系统的组合学习'},
    }


@pytest.mark.parametrize('with_citation', [True, False])
def test_input_preserves_paper_fields_and_does_not_share_nested_values(paper, with_citation):
    if not with_citation:
        paper.pop('citation')
    inputs = {'topic': TOPIC, 'papers': [paper]}
    normalized = contracts.validate_input('literature_review', inputs)
    assert normalized['papers'] == [paper]
    normalized['papers'][0]['user_annotations']['focus'] = '关注可扩展性'
    assert paper['user_annotations']['focus'] == '同步并行系统的组合学习'


@pytest.mark.parametrize('field', ['id', 'title', 'text', 'citation'])
def test_rejects_empty_paper_fields(paper, field):
    paper[field] = ''
    with pytest.raises(ValueError, match=rf'paper\.{field}'):
        contracts.validate_input('literature_review', {'topic': TOPIC, 'papers': [paper]})


def test_rejects_duplicate_paper_ids(paper):
    with pytest.raises(ValueError, match='论文 id 重复'):
        contracts.validate_input('literature_review', {'topic': TOPIC, 'papers': [paper, copy.deepcopy(paper)]})


def test_materials_preserve_papers_and_citations_for_downstream_steps(paper):
    materials = {
        'topic': TOPIC, 'papers': [paper], 'evidence': paper['text'],
        'question': '组合式主动学习在时间同步系统中有哪些适用条件和限制？',
    }
    pool = workflow.pool_from_business(materials)
    for step in ('literature_review', 'refine_topic', 'experiment', 'write_document', 'reading_reflection'):
        inputs = contracts.validate_input(step, workflow.business_input(step, pool))
        assert inputs['evidence'] == materials['evidence']
        if 'papers' in inputs:
            assert inputs['papers'] == [paper]
            inputs['papers'][0]['user_annotations']['focus'] = '关注可扩展性'
            assert workflow.material(pool, 'papers')['content'] == [paper]


@pytest.mark.skipif(
    os.environ.get('PAPER_REVIEW_LIVE') != '1',
    reason='设置 PAPER_REVIEW_LIVE=1，并配置真实模型后执行。',
)
def test_real_search_generates_citations():
    inputs = {
        'topic': TOPIC,
        'request': '使用 arXiv 检索1篇相关论文并综述，正文约200字。',
    }
    before = copy.deepcopy(inputs)
    result = api.run_algorithm('literature_review', inputs)
    assert inputs == before
    assert result['is_demo'] is False
    assert result['papers']
    for paper in result['papers']:
        assert paper['reading']
        assert paper['text'].strip()
        assert not paper['citation'].startswith('[')
        assert f'[{paper["id"]}]' in result['evidence']
        assert paper['citation'] in result['evidence']
    without_citation = copy.deepcopy(result)
    without_citation['papers'][0].pop('citation')
    with pytest.raises(ValueError, match=r'paper\.citation'):
        contracts.validate_output('literature_review', without_citation)
