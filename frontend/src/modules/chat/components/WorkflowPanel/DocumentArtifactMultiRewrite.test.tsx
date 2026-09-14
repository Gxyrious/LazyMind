import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import i18n from '@/i18n';
import EditableBlock from '../MarkdownViewer/EditableBlock';
import {DocumentArtifactEditor} from './DocumentArtifactEditor';
import type {SlotRevision} from '@/modules/chat/store/workflowPanel';
const formFailures=vi.hoisted(()=>[] as unknown[]);
const api=vi.hoisted(()=>({polishEditableSelection:vi.fn(),patchEditableBlock:vi.fn(),previewDocumentAction:vi.fn(),executeDocumentAction:vi.fn(),getDocumentArtifact:vi.fn()}));
vi.mock('@/modules/chat/utils/request',async original=>({...await original<typeof import('@/modules/chat/utils/request')>(),WorkflowSessionApi:()=>api,PromptServiceApi:()=>api,ChatServiceApi:()=>api}));
vi.mock('./useDocumentCopy',()=>({useDocumentCopy:()=>{}}));
vi.mock('./ArtifactRewriteDialog',async original=>({...await original<typeof import('./ArtifactRewriteDialog')>(),ArtifactRewriteDialog:({open,selection,requestPreview,onPreviewReady,onClose}:any)=>open?<button onClick={async()=>{try{onPreviewReady(await requestPreview('Make clearer',selection));onClose();}catch(error){formFailures.push(error);}}}>生成预览</button>:null}));
vi.mock('./MarkdownArtifactEditor',()=>({MarkdownArtifactEditor:({markdown,onRewriteSelection,onContentChange,allowMultipleParagraphs,readOnly}:any)=><div>
 <article>{markdown}</article><button disabled={readOnly} onClick={()=>onContentChange('Unsaved edit')}>模拟编辑</button>
 <button disabled={!allowMultipleParagraphs||readOnly} onClick={()=>onRewriteSelection({supported:true,paragraph:document.createElement('p'),text:'First Last',sourceRanges:[{selected_text:'First',start:0,end:5},{selected_text:'Last',start:13,end:17}]})}>选择两段</button></div>}));
const source='First\n\nKeep\n\nLast',candidate='Clear\n\nKeep\n\nBetter';
const slot={artifact_id:'artifact',slot_id:'flat_draft_document',revision:3,draft_version:7,artifact_value:{text:source},document:{representation:'markdown',editable:true,capabilities:['save','rewrite_selection']}} as SlotRevision;
const preview={representation:'markdown',results:[
 {target:{type:'block',block_type:'paragraph',target_start:0,target_end:5},preview:{old_text:'First',new_text:'Clear'},patch:{type:'string_replace_set',payload:{}}},
 {target:{type:'block',block_type:'paragraph',target_start:13,target_end:17},preview:{old_text:'Last',new_text:'Better'},patch:{type:'string_replace_set',payload:{}}},
],artifact:{content_type:'text',value:candidate},commit:{token:'00000000000000000000000000000001'}};
beforeEach(async()=>{vi.clearAllMocks();formFailures.length=0;await i18n.changeLanguage('zh-CN');api.previewDocumentAction.mockResolvedValue({data:{data:preview}});api.executeDocumentAction.mockResolvedValue({data:{data:{artifact_id:'saved'}}});api.getDocumentArtifact.mockResolvedValue({data:{result:{artifact_id:'saved',revision:4,draft_version:1,value:{text:candidate}}}});});
async function openPreview(){fireEvent.click(await screen.findByRole('button',{name:'选择两段'}));fireEvent.click(await screen.findByRole('button',{name:'生成预览'}));await screen.findByRole('button',{name:'应用全部修改'});}
it('submits both source ranges and applies the complete candidate with one commit token',async()=>{
 render(<DocumentArtifactEditor slot={slot} sessionId='session'/>);await openPreview();
 expect(api.previewDocumentAction.mock.calls[0][1].input.selection_ranges).toHaveLength(2);
 expect(api.executeDocumentAction).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'应用全部修改'}));
 await waitFor(()=>expect(screen.getByRole('article')).toHaveTextContent('Clear Keep Better'));
 expect(api.executeDocumentAction).toHaveBeenCalledTimes(1);expect(api.executeDocumentAction.mock.calls[0][1]).toEqual({action:'rewrite_selection',base_revision:3,base_draft_version:7,input:{commit_token:preview.commit.token}});
});
it('canceling the multi-paragraph preview preserves the document',async()=>{
 render(<DocumentArtifactEditor slot={slot} sessionId='session'/>);await openPreview();fireEvent.click(screen.getByRole('button',{name:'放弃本次润色'}));
 expect(api.executeDocumentAction).not.toHaveBeenCalled();expect(screen.getByRole('article')).toHaveTextContent('First Keep Last');
});
it('does not overwrite edits made while the model was generating',async()=>{
 let resolve!:(value:unknown)=>void;api.previewDocumentAction.mockImplementation(()=>new Promise(r=>{resolve=r;}));
 render(<DocumentArtifactEditor slot={slot} sessionId='session'/>);fireEvent.click(await screen.findByRole('button',{name:'选择两段'}));fireEvent.click(screen.getByRole('button',{name:'生成预览'}));
 fireEvent.click(screen.getByRole('button',{name:'模拟编辑'}));await act(async()=>resolve({data:{data:preview}}));
 fireEvent.click(await screen.findByRole('button',{name:'应用全部修改'}));expect(await screen.findByRole('alert')).toHaveTextContent('正文可能已变化');expect(api.executeDocumentAction).not.toHaveBeenCalled();
});
it('rejects a newer server revision without applying an old preview',async()=>{
 const view=render(<DocumentArtifactEditor slot={slot} sessionId='session'/>);await openPreview();
 view.rerender(<DocumentArtifactEditor slot={{...slot,artifact_id:'newer',revision:4,draft_version:1,artifact_value:{text:'External change'}}} sessionId='session'/>);
 await screen.findByText('External change');fireEvent.click(screen.getByRole('button',{name:'应用全部修改'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('正文可能已变化');expect(api.executeDocumentAction).not.toHaveBeenCalled();
});

it('applies ordinary chat multi-paragraph results through the persisted message API',async()=>{
 api.polishEditableSelection.mockResolvedValue({data:{results:preview.results.map(item=>({content:item.preview.new_text,old_content:item.preview.old_text,...item.target}))}});
 api.patchEditableBlock.mockResolvedValue({});
 render(<EditableBlock value={source} conversationId='conversation' historyId='history'/>);await openPreview();
 expect(api.polishEditableSelection.mock.calls[0][0].selection_ranges).toHaveLength(2);
 expect(api.patchEditableBlock).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'应用全部修改'}));
 await waitFor(()=>expect(api.patchEditableBlock).toHaveBeenCalledTimes(1));
 expect(api.patchEditableBlock.mock.calls[0][0]).toEqual({conversation_id:'conversation',history_id:'history',base_content:source,content:candidate});
 expect(screen.getByRole('article')).toHaveTextContent('Clear Keep Better');
});
it('keeps ordinary chat edits made during generation when applying a preview',async()=>{
 let resolve!:(value:unknown)=>void;api.polishEditableSelection.mockImplementation(()=>new Promise(r=>{resolve=r;}));
 render(<EditableBlock value={source} conversationId='conversation' historyId='history'/>);
 fireEvent.click(await screen.findByRole('button',{name:'选择两段'}));fireEvent.click(screen.getByRole('button',{name:'生成预览'}));fireEvent.click(screen.getByRole('button',{name:'模拟编辑'}));
 await act(async()=>resolve({data:{results:preview.results.map(item=>({content:item.preview.new_text,old_content:item.preview.old_text,...item.target}))}}));
 fireEvent.click(await screen.findByRole('button',{name:'应用全部修改'}));expect(await screen.findByRole('alert')).toHaveTextContent('正文可能已变化');expect(api.patchEditableBlock).not.toHaveBeenCalled();
});
it('rejects a forged ordinary chat target that includes the unselected gap',async()=>{
 api.polishEditableSelection.mockResolvedValue({data:{results:[{old_content:source,content:'All changed',target_start:0,target_end:17}]}});
 render(<EditableBlock value={source} conversationId='conversation' historyId='history'/>);
 fireEvent.click(await screen.findByRole('button',{name:'选择两段'}));fireEvent.click(screen.getByRole('button',{name:'生成预览'}));
 await waitFor(()=>expect(formFailures).toHaveLength(1));expect(api.patchEditableBlock).not.toHaveBeenCalled();
});
