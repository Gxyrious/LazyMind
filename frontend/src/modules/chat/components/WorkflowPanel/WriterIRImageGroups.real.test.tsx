import { useState } from 'react';
import { fireEvent, render } from '@testing-library/react';
import { expect, it } from 'vitest';
import { WriterIRDocumentEditor } from './WriterIRDocumentEditor';
import type { WriterDocument } from './writerIR';

it('结构化正文保留独立图片记录，并在选择后预览、排序和恢复', () => {
  let current: WriterDocument = { document_id: 'article', title: '城市绿意', stage: 'final', blocks: [
    { node_id: 'section', type: 'heading', content: '公园', children: [
      { node_id: 'first', type: 'image', content: '小路', references: [{ type: 'media_asset', path: 'https://example.com/a.jpg' }] },
      { node_id: 'second', type: 'image', content: '长椅', references: [{ type: 'media_asset', path: 'https://example.com/b.jpg' }] },
      { node_id: 'text', type: 'paragraph', content: '沿途正文' },
      { node_id: 'single', type: 'image', content: '草地', references: [{ type: 'media_asset', path: 'https://example.com/c.jpg' }] },
    ] },
  ] };
  function Editor() {
    const [document, setDocument] = useState(current);
    return <WriterIRDocumentEditor document={document} ariaLabel='正文' onFocus={() => {}} onBlur={() => {}}
      onChange={value => { current = value; setDocument(value); }} />;
  }
  const { container, getByRole } = render(<Editor />);
  expect(container.querySelectorAll('.writer-image-group')).toHaveLength(1);
  expect(current.metadata?.image_groups).toBeUndefined();
  fireEvent.click(getByRole('button', { name: '设为滑动图组' }));
  expect(container.querySelector('.writer-image-group')).toHaveAttribute('data-layout', 'sliding');
  fireEvent.click(getByRole('button', { name: '调整图片顺序' }));
  fireEvent.click(getByRole('button', { name: '图片 2 向前移动' }));
  expect(current.blocks[0].children?.map(block => block.node_id)).toEqual(['second', 'first', 'text', 'single']);
  fireEvent.click(getByRole('button', { name: '恢复纵向排列' }));
  expect(container.querySelector('.writer-image-group')).toHaveAttribute('data-layout', 'vertical');
  expect(container.querySelectorAll('img')).toHaveLength(3);
});
