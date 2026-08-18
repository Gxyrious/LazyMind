import { describe, expect, it } from 'vitest';
import { isWriterSystemAnchorBlock } from './writerIR';
import {
  applyWriterMarkdownInternalReference,
  collectWriterMarkdownOutline,
  collectWriterMarkdownReferenceTargets,
  restoreWriterMarkdownInternalReferenceLabels,
  writerMarkdownForEditor,
  writerMarkdownForSave,
  writerMarkdownInternalReference,
} from './writerMarkdownAnchors';

describe('Writer Markdown system anchors', () => {
  it('keeps system anchors round-trippable through MDXEditor', () => {
    const source = '# 标题\n\n<a id="block-sec-1"></a>\n## 1 章节';
    const editorValue = writerMarkdownForEditor(source);

    expect(editorValue).toContain('<a id="block-sec-1" />');
    expect(writerMarkdownForSave(editorValue)).toBe(source);
  });

  it('does not rewrite unrelated HTML anchors', () => {
    const source = '<a id="custom"></a>正文';

    expect(writerMarkdownForEditor(source)).toBe(source);
    expect(writerMarkdownForSave(source)).toBe(source);
  });

  it('identifies only IR paragraphs that contain a system anchor', () => {
    expect(isWriterSystemAnchorBlock({
      node_id: 'anchor-1',
      type: 'paragraph',
      content: '<a id="block-sec-1" />',
    })).toBe(true);
    expect(isWriterSystemAnchorBlock({
      node_id: 'paragraph-1',
      type: 'paragraph',
      content: '<a id="custom"></a>',
    })).toBe(false);
  });

  it('collects paired and editor-form anchors with their heading labels', () => {
    const source = [
      '<a id="block-sec-1"></a>',
      '## 1 系统设计',
      '',
      '<a id="block-sec-2" />',
      '### 1.1 接口设计',
    ].join('\n');

    expect(collectWriterMarkdownReferenceTargets(source)).toEqual([
      { anchorId: 'block-sec-1', label: '1 系统设计' },
      { anchorId: 'block-sec-2', label: '1.1 接口设计' },
    ]);
  });

  it('collects the Markdown title and anchored heading levels for the table of contents', () => {
    const source = [
      '# 产品架构说明',
      '',
      '<a id="block-sec-1"></a>',
      '## 1 系统设计',
      '',
      '<a id="block-sec-2" />',
      '### 1.1 接口设计',
      '',
      '```markdown',
      '<a id="block-fake" />',
      '## 代码块内标题',
      '```',
    ].join('\n');

    expect(collectWriterMarkdownOutline(source)).toEqual({
      title: '产品架构说明',
      items: [
        { anchorId: 'block-sec-1', label: '1 系统设计', level: 2 },
        { anchorId: 'block-sec-2', label: '1.1 接口设计', level: 3 },
      ],
    });
  });

  it('constructs an internal Markdown link from selected text and an anchor', () => {
    expect(writerMarkdownInternalReference('第 1 节', 'block-sec-1'))
      .toBe('[第 1 节](#block-sec-1)');
  });

  it('adds a reference around the original selected wording without moving it', () => {
    const paragraph = '潮水退去后，他仍听见深渊的低语。';
    const source = `# 标题\n\n${paragraph}`;

    expect(applyWriterMarkdownInternalReference(source, paragraph, 6, '他仍听见', 'block-sec-1'))
      .toBe('# 标题\n\n潮水退去后，[他仍听见](#block-sec-1)深渊的低语。');
  });

  it('locates a later selection when the paragraph already contains a reference', () => {
    const source = '详见[前文](#block-sec-1)，他仍听见深渊的低语。';
    const paragraph = '详见前文，他仍听见深渊的低语。';

    expect(applyWriterMarkdownInternalReference(source, paragraph, 5, '他仍听见', 'block-sec-2'))
      .toBe('详见[前文](#block-sec-1)，[他仍听见](#block-sec-2)深渊的低语。');
  });

  it('restores the user wording after server numbering materialization', () => {
    const source = '详见[前文的约定](#block-sec-1)。';
    const materialized = '详见[第1章](#block-sec-1)。';

    expect(restoreWriterMarkdownInternalReferenceLabels(materialized, source)).toBe(source);
  });
});
