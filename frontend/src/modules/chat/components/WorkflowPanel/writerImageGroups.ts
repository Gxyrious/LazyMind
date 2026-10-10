import { fromMarkdown } from 'mdast-util-from-markdown';
import { frontmatterFromMarkdown } from 'mdast-util-frontmatter';
import { frontmatter } from 'micromark-extension-frontmatter';
import { dump, load } from 'js-yaml';
import MarkdownIt from 'markdown-it';
import { isWriterSystemAnchorBlock, type WriterBlock, type WriterDocument } from './writerIR';
import { writerMarkdownForEditing } from './writerMarkdownAnchors';

export interface WriterImageRef { source: string; occurrence: number }
export interface WriterImageGroup { images: WriterImageRef[]; layout: 'sliding' | 'vertical' }
export interface WriterImageCandidate { images: WriterImageRef[]; nodeIds?: string[] }
interface MarkdownToken { type: string; content: string; children?: MarkdownToken[]; attrGet: (name: string) => string | null }

function parseGroupMarkdown(markdown: string) {
  const node = fromMarkdown(markdown, { extensions: [frontmatter(['yaml'])], mdastExtensions: [frontmatterFromMarkdown(['yaml'])] }).children[0];
  if (node?.type !== 'yaml') return { data: {} as Record<string, unknown>, content: markdown };
  const data = load(node.value) ?? {};
  if (typeof data !== 'object' || Array.isArray(data)) throw new Error('文档元数据格式无效');
  return { data: data as Record<string, unknown>, content: markdown.slice(node.position!.end.offset!).replace(/^\r?\n/, '') };
}

export function imageGroupKey(images: WriterImageRef[]): string {
  return JSON.stringify(images.map(image => JSON.stringify(image)).sort());
}

export function imageGroups(value: unknown): WriterImageGroup[] {
  if (value == null) return [];
  if (!Array.isArray(value)) throw new Error('图片组设置格式无效');
  return value.map(group => {
    if (!group || !['sliding', 'vertical'].includes(group.layout) || !Array.isArray(group.images) || group.images.length < 2
      || group.images.some((image: WriterImageRef) => typeof image.source !== 'string' || !image.source || !Number.isInteger(image.occurrence) || image.occurrence < 0)
      || new Set(group.images.map((image: WriterImageRef) => JSON.stringify(image))).size !== group.images.length) throw new Error('图片组设置格式无效');
    return { images: group.images.map((image: WriterImageRef) => ({ source: image.source, occurrence: image.occurrence })), layout: group.layout };
  });
}

export function imageGroupLayout(groups: WriterImageGroup[], images: WriterImageRef[]) {
  return groups.find(group => imageGroupKey(group.images) === imageGroupKey(images))?.layout;
}

export function setImageGroup(groups: WriterImageGroup[], images: WriterImageRef[], layout: WriterImageGroup['layout']) {
  return [...groups.filter(group => imageGroupKey(group.images) !== imageGroupKey(images)), { images, layout }];
}

export function imageSource(block: WriterBlock): string {
  const reference = block.references?.find(item => item.type === 'media_asset')
    ?? block.references?.find(item => item.type === 'preview_asset')
    ?? block.references?.find(item => item.type === 'wechat_image');
  return String(reference?.url ?? reference?.path ?? reference?.id ?? '');
}

export function irImageCandidates(document: WriterDocument): WriterImageCandidate[] {
  const candidates: WriterImageCandidate[] = [];
  const counts = new Map<string, number>();
  const visit = (blocks: WriterBlock[]) => {
    let current: WriterImageCandidate = { images: [], nodeIds: [] };
    const finish = () => { if (current.images.length >= 2) candidates.push(current); current = { images: [], nodeIds: [] }; };
    for (const block of blocks) {
      if (block.type === 'image' && !block.children?.length) {
        const source = imageSource(block);
        const occurrence = counts.get(source) ?? 0;
        counts.set(source, occurrence + 1);
        current.images.push({ source, occurrence }); current.nodeIds!.push(block.node_id);
      } else { finish(); if (block.children?.length) visit(block.children); }
    }
    finish();
  };
  visit(document.blocks);
  return candidates;
}

export function markdownImageCandidates(markdown: string): WriterImageCandidate[] {
  const tokens = new MarkdownIt({ html: true }).parse(writerMarkdownForEditing(parseGroupMarkdown(markdown).content), {}) as MarkdownToken[];
  const counts = new Map<string, number>();
  const result: WriterImageCandidate[] = [];
  let current: WriterImageRef[] = [];
  const finish = () => { if (current.length >= 2) result.push({ images: current }); current = []; };
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    if (token.type === 'paragraph_open' && tokens[index + 1]?.type === 'inline') {
      const children = tokens[index + 1].children ?? [];
      const images = children.filter(child => child.type === 'image').map(child => {
        const source = child.attrGet('src') ?? '';
        const occurrence = counts.get(source) ?? 0; counts.set(source, occurrence + 1);
        return { source, occurrence };
      });
      if (images.length && children.every(child => child.type === 'image' || child.type === 'softbreak' || child.type === 'hardbreak'
        || (child.type === 'html_inline' && isWriterSystemAnchorBlock({ node_id: '', type: 'paragraph', content: child.content })))) current.push(...images);
      else finish();
      index += 2; continue;
    }
    // 系统锚点不会中断相邻图片。
    if (token.type === 'html_block' && isWriterSystemAnchorBlock({ node_id: '', type: 'paragraph', content: token.content })) continue;
    finish();
  }
  finish(); return result;
}

export function documentImageGroups(value: string | WriterDocument) {
  return imageGroups(typeof value === 'string' ? parseGroupMarkdown(value).data.writer_image_groups : value.metadata?.image_groups);
}

export function pendingImageGroups(value: string | WriterDocument) {
  const groups = documentImageGroups(value);
  const candidates = typeof value === 'string' ? markdownImageCandidates(value) : irImageCandidates(value);
  return candidates.filter(candidate => candidate.images.length >= 3 && !imageGroupLayout(groups, candidate.images));
}

export function keepVerticalImageGroups(value: string | WriterDocument): string | WriterDocument {
  let groups = documentImageGroups(value);
  for (const candidate of pendingImageGroups(value)) groups = setImageGroup(groups, candidate.images, 'vertical');
  if (typeof value !== 'string') return { ...value, metadata: { ...value.metadata, image_groups: groups } };
  const parsed = parseGroupMarkdown(value);
  return `---\n${dump({ ...parsed.data, writer_image_groups: groups })}---\n\n${parsed.content.trimStart()}`;
}
