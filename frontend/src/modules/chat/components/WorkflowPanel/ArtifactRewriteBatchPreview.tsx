import {useRef,useState} from 'react';
import {Alert,Button,Modal,Space} from 'antd';
import {useTranslation} from 'react-i18next';
import type {RewriteSelectionPreview} from '@/modules/chat/utils/request';
import {renderInlineDiff} from './ArtifactRewriteDialog';

/** One candidate is committed atomically; per-paragraph diffs are inspection only. */
export function ArtifactRewriteBatchPreview({preview,onApply,onCancel}: {
 preview: RewriteSelectionPreview; onApply:()=>Promise<unknown>; onCancel:()=>void;
}) {
 const {t}=useTranslation();const [busy,setBusy]=useState(false),[failed,setFailed]=useState(false);const running=useRef(false);
 const apply=async()=>{if(running.current)return;running.current=true;setBusy(true);setFailed(false);
  try{await onApply();}catch{setFailed(true);}finally{running.current=false;setBusy(false);}};
 return <Modal open width={860} title={t('chat.artifactRewrite.batchTitle',{count:preview.results?.length})}
  onCancel={()=>{if(!busy)onCancel();}} closable={!busy} maskClosable={false}
  footer={<Space><Button disabled={busy} onClick={onCancel}>{t('chat.artifactRewrite.batchReject')}</Button>
   <Button type='primary' loading={busy} onClick={()=>void apply()}>{t('chat.artifactRewrite.batchApply')}</Button></Space>}>
  <p>{t('chat.artifactRewrite.batchHint')}</p>
  {failed && <Alert type='error' showIcon message={t('chat.artifactRewrite.batchFailed')} />}
  <div style={{maxHeight:'60vh',overflowY:'auto'}}>
   {preview.results?.map((item,index)=><section key={item.target.node_id ?? item.target.target_start ?? index} style={{marginBlock:20}}>
    <h4>{t('chat.artifactRewrite.batchParagraph',{index:index+1})}</h4>
    <div style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',lineHeight:1.7}}>{renderInlineDiff(item.preview.old_text,item.preview.new_text)}</div>
   </section>)}
  </div>
 </Modal>;
}
