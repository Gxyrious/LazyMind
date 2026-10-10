import { createRef } from 'react';
import { act, fireEvent, render, waitFor } from '@testing-library/react';
import { MDXEditor, frontmatterPlugin, headingsPlugin, imagePlugin, type MDXEditorMethods } from '@mdxeditor/editor';
import { expect, it } from 'vitest';
import MarkdownIt from 'markdown-it';
import { writerImageGroupPlugin } from './writerImageGroupPlugin';
import { documentImageGroups, markdownImageCandidates } from './writerImageGroups';

it('实际 MDXEditor 可以设置、排序、恢复并重新打开图片组', async () => {
  const editor = createRef<MDXEditorMethods>();
  const markdown = '# 文章\n\n![第一张](https://example.com/a.png)\n\n![第二张](https://example.com/b.png)\n\n正文\n\n![单张](https://example.com/c.png)';
  const { container, getByRole } = render(<MDXEditor ref={editor} markdown={markdown}
    plugins={[headingsPlugin(), imagePlugin(), frontmatterPlugin(), writerImageGroupPlugin()]} />);
  await waitFor(() => expect(getByRole('button', { name: '设为滑动图组' })).toBeInTheDocument());
  expect(container.querySelectorAll('.writer-image-group')).toHaveLength(1);
  expect(documentImageGroups(editor.current!.getMarkdown())).toEqual([]);
  await act(async () => fireEvent.click(getByRole('button', { name: '设为滑动图组' })));
  expect(container.querySelector('.writer-image-group')).toHaveAttribute('data-layout', 'sliding');
  expect(documentImageGroups(editor.current!.getMarkdown())[0].layout).toBe('sliding');
  await act(async () => fireEvent.click(getByRole('button', { name: '调整图片顺序' })));
  await act(async () => fireEvent.click(getByRole('button', { name: '图片 2 向前移动' })));
  expect(markdownImageCandidates(editor.current!.getMarkdown())[0].images.map(image => image.source)).toEqual([
    'https://example.com/b.png', 'https://example.com/a.png',
  ]);
  const saved = editor.current!.getMarkdown();
  await act(async () => editor.current!.setMarkdown(saved));
  await waitFor(() => expect(container.querySelector('.writer-image-group')).toHaveAttribute('data-layout', 'sliding'));
  await act(async () => fireEvent.click(getByRole('button', { name: '恢复纵向排列' })));
  expect(container.querySelector('.writer-image-group')).toHaveAttribute('data-layout', 'vertical');
  expect(documentImageGroups(editor.current!.getMarkdown())[0].layout).toBe('vertical');
  const tokens = new MarkdownIt().parse(editor.current!.getMarkdown(), {}) as Array<{ children?: Array<{ type: string }> }>;
  expect(tokens.flatMap(token => token.children ?? []).filter(token => token.type === 'image')).toHaveLength(3);
});

it('仅由换行隔开的连续图片可以设置滑动样式，单张图片保留原样', async () => {
  const editor = createRef<MDXEditorMethods>();
  const { container, getByRole } = render(<MDXEditor ref={editor}
    markdown={'![第一张](https://example.com/a.png)\n![第二张](https://example.com/b.png)\n\n正文\n\n![单张](https://example.com/c.png)\n'}
    plugins={[imagePlugin(), frontmatterPlugin(), writerImageGroupPlugin()]} />);
  await waitFor(() => expect(getByRole('button', { name: '设为滑动图组' })).toBeInTheDocument());
  expect(container.querySelectorAll('.writer-image-group')).toHaveLength(1);
  await act(async () => fireEvent.click(getByRole('button', { name: '设为滑动图组' })));
  expect(markdownImageCandidates(editor.current!.getMarkdown())[0].images).toHaveLength(2);
  await act(async () => fireEvent.click(getByRole('button', { name: '调整图片顺序' })));
  await act(async () => fireEvent.click(getByRole('button', { name: '图片 2 向前移动' })));
  expect(markdownImageCandidates(editor.current!.getMarkdown())[0].images.map(image => image.source)).toEqual([
    'https://example.com/b.png', 'https://example.com/a.png',
  ]);
});
