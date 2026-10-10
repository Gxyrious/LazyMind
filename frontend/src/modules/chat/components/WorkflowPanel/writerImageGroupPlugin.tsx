import {
  addComposerChild$, addExportVisitor$, addLexicalNode$, createRootEditorSubscription$,
  realmPlugin, rootEditor$, useCellValues, ImageNode, FrontmatterNode, $createFrontmatterNode,
} from '@mdxeditor/editor';
import {
  $applyNodeReplacement, $createParagraphNode, $getRoot, $isElementNode, $isParagraphNode, $getNodeByKey, $isLineBreakNode, $isTextNode,
  ElementNode, RootNode, setDOMUnmanaged, type LexicalNode, type NodeKey, type SerializedElementNode,
} from 'lexical';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { dump, load } from 'js-yaml';
import { WriterImageGroupControls } from './WriterImageGroupControls';
import { imageGroupKey, imageGroupLayout, imageGroups, setImageGroup, type WriterImageRef } from './writerImageGroups';
import './writerImageGroups.css';

class WriterImageGroupNode extends ElementNode {
  static getType() { return 'writer-image-group'; }
  static clone(node: WriterImageGroupNode) { return new WriterImageGroupNode(node.__key); }
  constructor(key?: NodeKey) { super(key); }
  static importJSON(value: SerializedElementNode) { return $applyNodeReplacement(new WriterImageGroupNode()).updateFromJSON(value); }
  createDOM() {
    const element = document.createElement('section'); element.className = 'writer-image-group';
    const host = document.createElement('div'); host.className = 'writer-image-group-host'; host.contentEditable = 'false';
    setDOMUnmanaged(host);
    const children = document.createElement('div'); children.className = 'writer-image-group-images';
    element.append(host, children); return element;
  }
  getDOMSlot(element: HTMLElement) { return super.getDOMSlot(element).withElement(element.querySelector<HTMLElement>('.writer-image-group-images')!); }
  updateDOM() { return false; }
  canBeEmpty() { return false; }
}

function imageParagraph(node: LexicalNode) {
  return $isParagraphNode(node) && node.getChildren().some(child => child instanceof ImageNode)
    && node.getChildren().every(child => child instanceof ImageNode || $isLineBreakNode(child)
      || ($isTextNode(child) && !child.getTextContent().trim()));
}

function imageCount(node: LexicalNode): number {
  if (node instanceof ImageNode) return 1;
  return $isElementNode(node) ? node.getChildren().reduce((count, child) => count + imageCount(child), 0) : 0;
}

function metadata() {
  const node = $getRoot().getChildren().find(child => child instanceof FrontmatterNode) as FrontmatterNode | undefined;
  const data = (node ? load(node.getYaml()) : {}) as Record<string, unknown>;
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('文档元数据格式无效');
  return { node, data };
}

function updateLayout(images: WriterImageRef[], layout: 'sliding' | 'vertical') {
  const { node, data } = metadata();
  const yaml = dump({ ...data, writer_image_groups: setImageGroup(imageGroups(data.writer_image_groups), images, layout) });
  if (node) node.setYaml(yaml); else $getRoot().splice(0, 0, [$createFrontmatterNode(yaml)]);
}

function normalizeImageParagraphs(node: WriterImageGroupNode) {
  for (const child of node.getChildren()) {
    if (!$isParagraphNode(child)) throw new Error('图片容器格式无效');
    if (child.getChildrenSize() <= 1) continue;
    for (const image of child.getChildren().filter(item => item instanceof ImageNode)) {
      const paragraph = $createParagraphNode().setFormat(child.getFormatType());
      child.insertBefore(paragraph); paragraph.append(image);
    }
    child.remove();
  }
}

function groupState() {
  const counts = new Map<string, number>();
  const groups = imageGroups(metadata().data.writer_image_groups);
  const result: Array<{ key: string; images: WriterImageRef[]; layout?: 'sliding' | 'vertical' }> = [];
  const visit = (node: LexicalNode): WriterImageRef[] => {
    if (node instanceof ImageNode) {
      const source = node.getSrc(), occurrence = counts.get(source) ?? 0;
      counts.set(source, occurrence + 1); return [{ source, occurrence }];
    }
    const images = $isElementNode(node) ? node.getChildren().flatMap(visit) : [];
    if (node instanceof WriterImageGroupNode) result.push({ key: node.getKey(), images, layout: imageGroupLayout(groups, images) });
    return images;
  };
  visit($getRoot()); return result;
}

function GroupControls() {
  const [editor] = useCellValues(rootEditor$);
  const [groups, setGroups] = useState<ReturnType<typeof groupState>>([]);
  const [editable, setEditable] = useState(false);
  useEffect(() => {
    if (!editor) return;
    const refresh = () => {
      const state = editor.getEditorState().read(groupState);
      const fm = editor.getEditorState().read(() => metadata().node);
      if (fm) {
        const data = editor.getEditorState().read(() => metadata().data);
        const element = editor.getElementByKey(fm.getKey());
        if (element) element.hidden = Object.keys(data).every(key => key === 'writer_image_groups');
      }
      for (const group of state) {
        const element = editor.getElementByKey(group.key);
        element?.setAttribute('data-layout', group.layout ?? 'vertical');
        element?.setAttribute('data-image-group-key', imageGroupKey(group.images));
      }
      setGroups(state);
    };
    refresh(); setEditable(editor.isEditable());
    const unsubscribe = editor.registerUpdateListener(refresh);
    const unsubscribeEditable = editor.registerEditableListener(setEditable);
    editor.update(() => $getRoot().markDirty());
    return () => { unsubscribe(); unsubscribeEditable(); };
  }, [editor]);
  if (!editor) return null;
  return <>{groups.map(group => {
    const host = editor.getElementByKey(group.key)?.querySelector<HTMLElement>('.writer-image-group-host');
    return host && createPortal(<WriterImageGroupControls count={group.images.length} layout={group.layout} readOnly={!editable}
      onLayout={layout => editor.update(() => {
        const node = $getNodeByKey(group.key);
        if (!(node instanceof WriterImageGroupNode)) throw new Error('图片组已经发生变化');
        if (layout === 'sliding') normalizeImageParagraphs(node);
        updateLayout(group.images, layout);
      })}
      onMove={(index, direction) => editor.update(() => {
        const node = $getNodeByKey(group.key);
        if (!(node instanceof WriterImageGroupNode)) throw new Error('图片组已经发生变化');
        normalizeImageParagraphs(node);
        const paragraphs = node.getChildren();
        const item = paragraphs[index], target = paragraphs[index + direction];
        if (!item || !target) throw new Error('图片移动位置无效');
        if (direction < 0) target.insertBefore(item); else target.insertAfter(item);
      })} />, host, group.key);
  })}</>;
}

export const writerImageGroupPlugin = realmPlugin({
  init(realm) {
    realm.pub(addLexicalNode$, WriterImageGroupNode);
    realm.pub(addComposerChild$, GroupControls);
    realm.pub(addExportVisitor$, {
      testLexicalNode: (node): node is WriterImageGroupNode => node instanceof WriterImageGroupNode,
      visitLexicalNode({ lexicalNode, mdastParent, actions }) { actions.visitChildren(lexicalNode, mdastParent); },
    });
    realm.pub(createRootEditorSubscription$, editor => editor.registerNodeTransform(RootNode, root => {
      let run: LexicalNode[] = [];
      const finish = () => {
        const count = run.reduce((total, item) => total + imageCount(item), 0);
        if (count >= 2 && !(run.length === 1 && run[0] instanceof WriterImageGroupNode)) {
          const group = $applyNodeReplacement(new WriterImageGroupNode()); run[0].insertBefore(group);
          for (const item of run) {
            if (item instanceof WriterImageGroupNode) { group.append(...item.getChildren()); item.remove(); }
            else group.append(item);
          }
        }
        run = [];
      };
      for (const child of root.getChildren()) {
        if (child instanceof WriterImageGroupNode && (!child.getChildren().every(imageParagraph)
          || imageCount(child) < 2)) {
          child.getChildren().forEach(item => child.insertBefore(item)); child.remove(); finish();
        } else if (imageParagraph(child) || child instanceof WriterImageGroupNode) run.push(child);
        else finish();
      }
      finish();
    }));
  },
});
