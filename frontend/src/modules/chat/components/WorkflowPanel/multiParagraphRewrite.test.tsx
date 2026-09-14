import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import i18n from '@/i18n';
import {ConfigProvider} from 'antd';
import {WriterIRDocumentEditor} from './WriterIRDocumentEditor';
import {ArtifactRewriteBatchPreview} from './ArtifactRewriteBatchPreview';
import {documentRewritePreview} from './documentRewritePreview';
import {selectedIRParagraphs} from './writerIRRewriteSelection';
import {markdownSelectionRange} from './writerMarkdownSource';
import {selectedMarkdownParagraph} from './artifactRewriteSelection';
const payload={representation:'markdown',results:[
 {target:{type:'block',block_type:'paragraph',target_start:0,target_end:5},preview:{old_text:'First',new_text:'Clear'},patch:{type:'string_replace_set',payload:{}}},
 {target:{type:'block',block_type:'paragraph',target_start:13,target_end:17},preview:{old_text:'Last',new_text:'Better'},patch:{type:'string_replace_set',payload:{}}},
],artifact:{content_type:'text',value:'Clear\n\nKeep\n\nBetter'},commit:{token:'00000000000000000000000000000001'}};
beforeEach(async()=>{await i18n.changeLanguage('zh-CN');Range.prototype.getBoundingClientRect=()=>({x:0,y:100,top:100,left:0,right:100,bottom:140,width:100,height:40,toJSON:()=>({})});});
it('keeps every paragraph diff and only commits on explicit confirmation',async()=>{
 const preview=documentRewritePreview(payload,3,7),apply=vi.fn(),cancel=vi.fn();
 render(<ConfigProvider theme={{token:{motion:false}}}><ArtifactRewriteBatchPreview preview={preview} onApply={apply} onCancel={cancel}/></ConfigProvider>);
 await waitFor(()=>expect(screen.getByText('Clear')).toBeVisible());expect(screen.getByText('Better')).toBeVisible();expect(apply).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'放弃本次润色'}));expect(cancel).toHaveBeenCalledTimes(1);expect(apply).not.toHaveBeenCalled();
 let finish!:()=>void;apply.mockImplementation(()=>new Promise<void>(resolve=>{finish=resolve;}));
 const button=screen.getByRole('button',{name:'应用全部修改'});fireEvent.click(button);fireEvent.click(button);expect(apply).toHaveBeenCalledTimes(1);
 await act(async()=>finish());
});
it('preserves the preview when applying fails',async()=>{
 const apply=vi.fn().mockRejectedValue(new Error('conflict'));
 render(<ConfigProvider theme={{token:{motion:false}}}><ArtifactRewriteBatchPreview preview={documentRewritePreview(payload,3,7)} onApply={apply} onCancel={vi.fn()}/></ConfigProvider>);
 fireEvent.click(screen.getByRole('button',{name:'应用全部修改'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('正文可能已变化');await waitFor(()=>expect(screen.getByText('Better')).toBeVisible());
});
it('maps cross-paragraph DOM selections to distinct Unicode source positions',()=>{
 const root=document.createElement('div');root.className='mdxeditor-root-contenteditable';root.innerHTML='<p>😀 Same.</p><p>Keep.</p><p>😀 Same.</p>';document.body.append(root);
 const paragraphs=root.querySelectorAll('p'),range=document.createRange();range.setStart(paragraphs[0].firstChild!,3);range.setEnd(paragraphs[2].firstChild!,7);
 const selection=globalThis.getSelection()!;selection.removeAllRanges();selection.addRange(range);
 const picked=selectedMarkdownParagraph(root,true)!;expect(picked.supported).toBe(true);
 const source='😀 Same.\n\nKeep.\n\n😀 Same.';
 const ranges=picked.paragraphSelections!.map(item=>markdownSelectionRange(source,item));
 expect(ranges).toHaveLength(3);expect(ranges[0].start).toBe(2);expect(ranges[2].start).toBe(16);
 for(const item of ranges)expect(Array.from(source).slice(item.start,item.end).join('')).toBe(item.selected_text);
 root.remove();
});
it('rejects selection crossing a heading',()=>{
 const root=document.createElement('div');root.innerHTML='<p>First.</p><h2>Heading</h2><p>Last.</p>';document.body.append(root);
 const range=document.createRange();range.selectNodeContents(root);globalThis.getSelection()!.removeAllRanges();globalThis.getSelection()!.addRange(range);
 expect(selectedMarkdownParagraph(root,true)?.supported).toBe(false);root.remove();
});
it('captures multiple IR paragraphs and rejects a read-only member',()=>{
 const root=document.createElement('div');root.innerHTML='<div data-node-id="one"><p data-writer-block-content>First.</p></div><div data-node-id="two"><p data-writer-block-content>Last.</p></div>';document.body.append(root);
 const range=document.createRange();range.selectNodeContents(root);globalThis.getSelection()!.removeAllRanges();globalThis.getSelection()!.addRange(range);
 const documentValue={document_id:'fixture',title:'Fixture',stage:'draft',blocks:[{node_id:'one',type:'paragraph',content:'First.'},{node_id:'two',type:'paragraph',content:'Last.',editable:true}]};
 expect(selectedIRParagraphs(root,documentValue)?.nodeSelections).toEqual([{node_id:'one',selected_text:'First.'},{node_id:'two',selected_text:'Last.'}]);
 documentValue.blocks[1].editable=false;expect(selectedIRParagraphs(root,documentValue)).toBeNull();root.remove();
});

it('exposes multi-paragraph polish from the real IR editor selection',async()=>{
 const onRewrite=vi.fn();
 const value={document_id:'fixture',title:'Fixture',stage:'draft',blocks:[{node_id:'one',type:'paragraph',content:'First.'},{node_id:'two',type:'paragraph',content:'Last.'}]};
 const {container}=render(<WriterIRDocumentEditor document={value} ariaLabel='IR editor' onChange={vi.fn()} onFocus={vi.fn()} onBlur={vi.fn()} allowMultipleParagraphs onRewriteSelection={onRewrite}/>);
 const paragraphs=container.querySelectorAll('[data-writer-block-content]');
 const range=document.createRange();range.setStart(paragraphs[0].firstChild!,1);range.setEnd(paragraphs[1].firstChild!,4);
 globalThis.getSelection()!.removeAllRanges();globalThis.getSelection()!.addRange(range);
 fireEvent(document,new Event('selectionchange'));
 fireEvent.click(await screen.findByRole('button',{name:String(i18n.t('chat.artifactRewrite.action'))}));
 expect(onRewrite).toHaveBeenCalledWith(expect.objectContaining({nodeSelections:[{node_id:'one',selected_text:'irst.'},{node_id:'two',selected_text:'Last'}]}));
});

it.each(['editing','reading'])('rejects IR selections crossing empty structures or the document title in %s',mode=>{
 for(const extra of ['<div data-node-id="divider"><hr></div>','<h1>Document title</h1>']) {
  const root=document.createElement('div');const attribute=mode==='editing'?'data-writer-block-content':'class="writer-ir__paragraph"';
  root.innerHTML=`<div data-node-id="one"><p ${attribute}>First.</p></div>${extra}<div data-node-id="two"><p ${attribute}>Last.</p></div>`;document.body.append(root);
  const range=document.createRange();range.selectNodeContents(root);globalThis.getSelection()!.removeAllRanges();globalThis.getSelection()!.addRange(range);
  const value={document_id:'fixture',title:'Fixture',stage:'draft',blocks:[{node_id:'one',type:'paragraph',content:'First.'},{node_id:'divider',type:'divider',content:''},{node_id:'two',type:'paragraph',content:'Last.'}]};
  expect(selectedIRParagraphs(root,value)).toBeNull();root.remove();
 }
});
