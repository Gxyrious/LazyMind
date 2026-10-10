import { expect, it } from 'vitest';
import { documentImageGroups, keepVerticalImageGroups, markdownImageCandidates, pendingImageGroups } from './writerImageGroups';

it('识别连续图片，并在标题、正文和其他内容位置结束图片组', () => {
  const markdown = '# 标题\n\n![a](a.png)\n\n![b](b.png)\n\n## 第二章\n\n![c](c.png)\n![d](d.png)\n![e](e.png)\n\n正文\n\n![f](f.png)\n\n正文\n\n![g](g.png)';
  expect(markdownImageCandidates(markdown).map(group => group.images.length)).toEqual([2, 3]);
  expect(pendingImageGroups(markdown)).toHaveLength(1);
  const chosen = keepVerticalImageGroups(markdown) as string;
  expect(pendingImageGroups(chosen)).toHaveLength(0);
  expect(documentImageGroups(chosen)[0].layout).toBe('vertical');
  expect(markdownImageCandidates(chosen).map(group => group.images.length)).toEqual([2, 3]);
});

it('重复图片保留独立出现次数', () => {
  expect(markdownImageCandidates('![a](same.png)\n\n![b](same.png)')[0].images).toEqual([
    { source: 'same.png', occurrence: 0 }, { source: 'same.png', occurrence: 1 },
  ]);
});

it('带编号信息的系统锚点保留发布提醒识别', () => {
  const source = ['a', 'b', 'c'].map(name => `<a id="block-${name}" data-writer-numbering="auto" />\n![${name}](${name}.png)`).join('\n\n');
  expect(markdownImageCandidates(source)[0].images).toHaveLength(3);
  expect(pendingImageGroups(source)).toHaveLength(1);
});
