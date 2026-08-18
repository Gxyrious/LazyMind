import { describe, expect, it } from 'vitest';

import {
  applyWriterBlockInternalReference,
  collectWriterReferenceTargets,
  restoreWriterInternalReferenceDisplayText,
  type WriterDocument,
} from './writerIR';

const document: WriterDocument = {
  document_id: 'writer-doc-1',
  stage: 'draft',
  title: '产品架构说明',
  blocks: [
    {
      node_id: 'sec-1',
      type: 'heading',
      numbering: { level: 1 },
      content: '1 系统设计',
      spans: [{ text: '1 系统设计', style: {} }],
    },
    {
      node_id: 'p-1',
      type: 'paragraph',
      content: '详见第 1 节。',
      spans: [{ text: '详见第 1 节。', style: {} }],
    },
  ],
};

describe('Writer IR cross references', () => {
  it('collects numbered IR blocks as reference targets', () => {
    expect(collectWriterReferenceTargets(document.blocks)).toEqual([
      { nodeId: 'sec-1', label: '1 系统设计', type: 'heading' },
    ]);
  });

  it('adds internal_ref styling only to the selected text range', () => {
    const revised = applyWriterBlockInternalReference(document, 'p-1', 2, 7, 'sec-1');
    const paragraph = revised.blocks[1];

    expect(paragraph.spans?.map((span) => span.text).join('')).toBe(paragraph.content);
    expect(paragraph.spans).toEqual([
      { text: '详见', style: {} },
      {
        text: '第 1 节',
        style: {
          link: {
            type: 'internal_ref',
            target_node_id: 'sec-1',
            display_text: '第 1 节',
          },
        },
      },
      { text: '。', style: {} },
    ]);
  });

  it('restores the user-authored label after server materialization', () => {
    const materialized: WriterDocument = {
      ...document,
      blocks: [
        document.blocks[0],
        {
          node_id: 'p-1',
          type: 'paragraph',
          content: '详见第1章。',
          spans: [
            { text: '详见', style: {} },
            {
              text: '第1章',
              style: {
                link: {
                  type: 'internal_ref',
                  target_node_id: 'sec-1',
                  display_text: '这里',
                },
              },
            },
            { text: '。', style: {} },
          ],
        },
      ],
    };

    const restored = restoreWriterInternalReferenceDisplayText(materialized);
    expect(restored.blocks[1].content).toBe('详见这里。');
    expect(restored.blocks[1].spans?.[1].text).toBe('这里');
  });
});
