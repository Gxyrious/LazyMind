import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Modal, Space } from 'antd';
import { useTranslation } from 'react-i18next';
import type { DocumentPublicationRecoveryRequest, DocumentPublicationStatus } from '@/api/generated/core-client';
import { WorkflowSessionApi } from '@/modules/chat/utils/request';

const terminal = new Set(['succeeded','failed_no_write','canceled','outcome_unknown_released','confirmed_detached']);
export function DocumentPublicationRecoveryPanel({ artifactId, slotId, itemIndex, refreshKey, publishing, readOnly, canApplyLocal, onAvailability, onResolved }: {
  artifactId: string; slotId: string; itemIndex: number; refreshKey: number; publishing: boolean; readOnly?: boolean;
  canApplyLocal: () => boolean; onAvailability: (allowed: boolean) => void; onResolved: () => void;
}) {
  const {t}=useTranslation();
  const [operation,setOperation]=useState<DocumentPublicationStatus>();
  const [loaded,setLoaded]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [now,setNow]=useState(Date.now());
  const alive=useRef(false),running=useRef(false),generation=useRef(0);
  const dialog=useRef<ReturnType<typeof Modal.confirm>>();
  const callbacks=useRef({canApplyLocal,onAvailability,onResolved});
  callbacks.current={canApplyLocal,onAvailability,onResolved};
  const silent={silentError:true};

  const load=useCallback(async()=>{
    const current=++generation.current;
    setBusy(true);setError('');
    try {
      const response=await WorkflowSessionApi().getPublicationForArtifact(artifactId,{silentError:true});
      if(alive.current && current===generation.current){setOperation(response.data.data.operation);setLoaded(true);setNow(Date.now());}
    } catch {
      if(alive.current && current===generation.current){setLoaded(false);setError('loadFailed');}
    } finally {if(alive.current && current===generation.current)setBusy(false);}
  },[artifactId]);
  useEffect(()=>{
    alive.current=true;
    return ()=>{alive.current=false;generation.current++;dialog.current?.destroy();};
  },[]);
  useEffect(()=>{void load();},[load,refreshKey]);
  useEffect(()=>{
    callbacks.current.onAvailability(loaded && !busy && !error && (!operation || terminal.has(operation.status)));
  },[loaded,busy,error,operation]);
  useEffect(()=>{
    if(operation?.status!=='write_started' || !operation.recovery_after) return;
    const delay=new Date(operation.recovery_after).getTime()-Date.now();
    if(delay<=0)return;
    const timer=window.setTimeout(()=>setNow(Date.now()),Math.min(delay+20,2147483647));
    return ()=>window.clearTimeout(timer);
  },[operation]);

  const run=async(action:'cancel'|'retry_local'|DocumentPublicationRecoveryRequest['action'],reason?:DocumentPublicationRecoveryRequest['reason'])=>{
    if(!operation || running.current || publishing || readOnly || !alive.current)return;
    if(action==='retry_local' && !callbacks.current.canApplyLocal()){setError('unsaved');return;}
    running.current=true;setBusy(true);setError('');
    const current=++generation.current;
    try {
      const api=WorkflowSessionApi();
      let status:DocumentPublicationStatus;
      if(action==='retry_local') {
        await api.retryPublicationLocal(operation.operation_id,silent);
        status=(await api.readPublication(operation.operation_id,silent)).data.data;
      } else if(action==='cancel') status=(await api.cancelPublication(operation.operation_id,silent)).data.data;
      else status=(await api.recoverPublication(operation.operation_id,{action,confirmed:action!=='check',reason},silent)).data.data;
      if(alive.current && current===generation.current){
        setOperation(status);setLoaded(true);setNow(Date.now());
        if(terminal.has(status.status))callbacks.current.onResolved();
      }
    } catch (failure) {
      const code=(failure as {response?:{data?:{data?:{code?:string}}}})?.response?.data?.data?.code;
      if(alive.current && current===generation.current)setError(code==='PROVIDER_SYNC_LOCAL_CONFLICT'?'localConflict':'actionFailed');
    } finally {running.current=false;if(alive.current && current===generation.current)setBusy(false);}
  };
  const confirm=(action:'release_unknown'|'keep_remote',reason?:DocumentPublicationRecoveryRequest['reason'])=>{
    const message=action==='keep_remote'?'keepRemoteWarning':reason==='user_verified_no_write'?'verifiedWarning':'unknownWarning';
    dialog.current=Modal.confirm({title:t(`chat.writerIR.publicationRecovery.${action==='keep_remote'?'keepRemote':'release'}`),
      content:t(`chat.writerIR.publicationRecovery.${message}`),okText:t('chat.writerIR.publicationRecovery.confirm'),cancelText:t('chat.writerIR.publicationRecovery.cancelDialog'),
      onOk:()=>run(action,reason)});
  };
  const label=(key:string)=>t(`chat.writerIR.publicationRecovery.${key}`);
  const disabled=busy || publishing || readOnly || (Boolean(error) && !['unsaved','localConflict'].includes(error));
  const actions=operation?.actions ?? [];
  const expired=operation?.status==='write_started' && operation.recovery_after && new Date(operation.recovery_after).getTime()<=now;
  if(!loaded && !error)return <span role='status'>{label('loading')}</span>;
  if(!operation && !error)return null;
  if(operation && ['failed_no_write','canceled'].includes(operation.status) && !error)return null;
  let target:string|undefined;
  try {const url=new URL(operation?.target_url ?? '');if(['https:','http:'].includes(url.protocol)&&!url.username&&!url.password)target=url.href;} catch { /* No verified target link is available. */ }
  const known=operation && ['preparing','write_started','outcome_unknown','provider_confirmed','local_conflict','local_persist_failed','succeeded','outcome_unknown_released','confirmed_detached'].includes(operation.status);
  return <Alert showIcon type={operation && terminal.has(operation.status)?'info':'warning'}
    message={label('title')}
    description={<Space direction='vertical' style={{width:'100%'}}>
      {operation && <>
        <span>{label(known?`states.${operation.status}`:'unknownState')}</span>
        {(operation.source_slot_id!==slotId || operation.item_index!==itemIndex) && <span>{label('otherDraft')}</span>}
        {target?<a href={target} target='_blank' rel='noreferrer'>{label('openTarget')}</a>:<span>{label('noTarget')}</span>}
        <details><summary>{label('details')}</summary><div style={{overflowWrap:'anywhere'}}>{operation.operation_id}</div><time dateTime={operation.updated_at}>{new Date(operation.updated_at).toLocaleString()}</time></details>
      </>}
      {error && <span role='alert'>{label(error)}</span>}
      <Space wrap>
        <Button disabled={busy || publishing} onClick={()=>void load()}>{label(error==='loadFailed'?'retryQuery':'refresh')}</Button>
        {actions.includes('cancel') && <Button disabled={disabled} onClick={()=>void run('cancel')}>{label('cancel')}</Button>}
        {(actions.includes('check') || expired) && <Button disabled={disabled} onClick={()=>void run('check')}>{label('check')}</Button>}
        {actions.includes('retry_local') && <Button disabled={disabled || error==='unsaved' || error==='localConflict'} onClick={()=>void run('retry_local')}>{label('retryLocal')}</Button>}
        {actions.includes('keep_remote') && <Button disabled={disabled} onClick={()=>confirm('keep_remote')}>{label('keepRemote')}</Button>}
        {actions.includes('release_unknown') && <>
          <Button disabled={disabled} onClick={()=>confirm('release_unknown','user_verified_no_write')}>{label('verifiedRelease')}</Button>
          <Button disabled={disabled} onClick={()=>confirm('release_unknown','accept_unknown')}>{label('release')}</Button>
        </>}
        {operation?.status==='succeeded' && operation.artifact_id!==artifactId && <Button disabled={disabled} onClick={()=>callbacks.current.onResolved()}>{label('updateDraft')}</Button>}
      </Space>
    </Space>} />;
}
