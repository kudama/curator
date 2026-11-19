'use strict';
// Keep the approved board stable; file preparation and other work never replace it.
const queueFileSelection=new Set();
const expandedWaitingQueues=new Set();
const QUEUE_FILE_KINDS=new Set(['join','rename','group']);
function foldWaitingQueue(lane,kind){
 const waiting=[...lane.children].filter(card=>card.dataset.queueWaiting==='true');
 if(waiting.length<=5)return;
 const remaining=waiting.slice(5),hidden=new Set(remaining),expanded=expandedWaitingQueues.has(kind),container=node('div',undefined,'queue-waiting-more');
 container.id='queue-more-'+kind;container.hidden=!expanded;container.append(...remaining);
 const toggle=button(expanded?'Show fewer':'Show '+remaining.length+' more',()=>{expandedWaitingQueues.has(kind)?expandedWaitingQueues.delete(kind):expandedWaitingQueues.add(kind);render();$('queue-toggle-'+kind)?.focus?.();},'text-button queue-waiting-toggle');
 toggle.id='queue-toggle-'+kind;toggle.setAttribute('aria-expanded',String(expanded));toggle.setAttribute('aria-controls',container.id);
 lane.replaceChildren(...[...lane.children].filter(card=>!hidden.has(card)),toggle,container);
}
function queueActiveFiles(){return (state.file_jobs||[]).filter(j=>['waiting','running'].includes(j.phase));}
function queueBoardTasks(){const owned=new Set(queueActiveFiles().map(j=>j.payload?.task).filter(Boolean));return state.tasks.filter(t=>!owned.has(t.id)&&['queued','running','publishing','awaiting_review','failed','blocked'].includes(t.status));}
function queueBoardAvailable(){return true;}
function queueOrphanCleanups(){return (state.cleanup_jobs||[]).filter(r=>r.phase!=='complete'&&!queueActiveFiles().some(j=>j.payload?.receipt===r.id));}
function queueIsRunning(){return (state.task_queues||[]).some(q=>q.active&&!q.paused)||queueActiveFiles().some(j=>j.phase==='running'&&!state.file_queue_paused)||(!Array.isArray(state.task_queues)&&Boolean(state.queue_running));}
function queueVisible(row){return queueMatchesLibrary(row)&&(!searchText||[row.title,catalogIndex().byId.get(row.asset)?.plex_path,TASK_LABELS[row.kind],row.operation].join(' ').toLocaleLowerCase().includes(searchText));}
function queueStatusMatches(status){return queueStatus==='all'||(queueStatus==='attention'?['failed','blocked'].includes(status):queueStatus==='running'?['running','publishing'].includes(status):status===queueStatus);}
function queueCountRows(){return [...queueBoardTasks(),...queueOrphanCleanups().map(r=>({...r,title:'Clean up originals',status:r.phase==='queued'?'queued':r.phase==='deleting'?'publishing':'blocked'})),...queueActiveFiles().map(j=>({...j,status:j.phase==='waiting'?'queued':'publishing'}))].filter(queueVisible);}
function renderQueueStatusLinks(){
 const nav=$('queue-status-links');nav.hidden=!['processing','review'].includes(screen);nav.replaceChildren();if(nav.hidden)return;
 const rows=queueCountRows();
 for(const [value,label] of [['all','All jobs'],['running','Processing'],['queued','Waiting'],['awaiting_review','Ready to review'],['attention','Needs attention']]){
  const count=rows.filter(r=>value==='all'||(value==='running'?['running','publishing'].includes(r.status):value==='attention'?['failed','blocked'].includes(r.status):r.status===value)).length;
  const control=button(label+' '+count,()=>{if(!prepareInspector())return;closeInspector(true);queueStatus=value;setScreen(value==='awaiting_review'?'review':'processing');},'text-button');
  const active=screen==='review'?value==='awaiting_review':queueStatus===value;control.classList.toggle('active',active);if(active)control.setAttribute('aria-current','page');nav.append(control);
 }
}
function mergeQueueOrder(full,visible,order){const chosen=new Set(visible),next=order[Symbol.iterator]();return full.map(id=>chosen.has(id)?next.next().value:id);}
function queueLaneIds(kind){return kind==='file_operations'?(state.file_queue||[]).map(r=>r.id):waitingSnapshot().filter(r=>state.tasks.find(t=>t.id===r.id)?.kind===kind).map(r=>r.id);}
function queueVisibleIds(kind){const rows=kind==='file_operations'?queueActiveFiles():state.tasks;return queueLaneIds(kind).filter(id=>rows.some(r=>r.id===id&&queueVisible(r)));}
async function changeFileOrder(order,expected=(state.file_queue||[]).map(r=>({...r}))){
 if(queueChangeBusy)return;queueChangeBusy=true;render();
 try{await api('file-queue/order',{expected,order});queueFileSelection.clear();}
 finally{queueChangeBusy=false;await refresh();}
}
function queueDrag(card,handle,row,file=false){
 card.dataset.waitingId=row.id;let origin=null,snapshot,visible;
 handle.onpointerdown=e=>{if(queueChangeBusy)return;e.preventDefault();origin=[e.clientX,e.clientY];snapshot=(file?state.file_queue:waitingSnapshot()).map(r=>({...r}));visible=queueVisibleIds(file?'file_operations':row.kind);queueDragging=true;handle.setPointerCapture(e.pointerId);};
 handle.onpointerup=e=>{if(!origin)return;const moved=Math.hypot(e.clientX-origin[0],e.clientY-origin[1])>5;origin=null;queueDragging=false;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-waiting-id]')?.dataset.waitingId;
  const order=moved?dropWaitingOrder(visible,row.id,target):null;
  if(order){const full=mergeQueueOrder(snapshot.map(r=>r.id),visible,order);run(()=>file?changeFileOrder(full,snapshot):changeWaitingQueue({order:full},snapshot));}else render();
 };
 handle.onpointercancel=()=>{origin=null;queueDragging=false;render();};
}
function queueLaneSelection(kind){
 const file=kind==='file_operations',selection=file?queueFileSelection:waitingSelection,visible=queueVisibleIds(kind),available=new Set(file?(state.file_queue||[]).map(r=>r.id):waitingSnapshot().map(r=>r.id));
 for(const id of selection)if(!available.has(id))selection.delete(id);
 const chosen=new Set(visible.filter(id=>selection.has(id))),controls=node('div',undefined,'queue-lane-actions');
 if(!visible.length||!['all','queued'].includes(queueStatus))return controls;
 const select=button(chosen.size===visible.length?'Clear selection':'Select all '+visible.length,()=>{for(const id of visible)chosen.size===visible.length?selection.delete(id):selection.add(id);render();},'text-button');select.disabled=queueChangeBusy;controls.append(select);
 if(!chosen.size)return controls;
 controls.append(node('span',chosen.size+' selected','muted'));
 for(const edge of ['top','bottom']){const move=button('Move to '+edge,()=>{const snapshot=(file?state.file_queue:waitingSnapshot()).map(r=>({...r})),order=mergeQueueOrder(snapshot.map(r=>r.id),visible,moveWaitingOrder(visible,chosen,edge));return file?changeFileOrder(order,snapshot):changeWaitingQueue({order},snapshot);},'text-button');move.disabled=queueChangeBusy;controls.append(move);}
 if(!file){const remove=button('Remove from queue',()=>changeWaitingQueue({remove:[...chosen]}),'text-button');remove.disabled=queueChangeBusy;controls.append(remove);}
 return controls;
}
function queueLaneControl(kind){
 const files=kind==='file_operations',info=(state.task_queues||[]).find(q=>q.kind===kind),running=files?queueActiveFiles().filter(j=>j.phase==='running').length:info?.running||0,waiting=queueLaneIds(kind).length,paused=files?state.file_queue_paused:Boolean(info?.paused);
 const active=files?running&&!paused:info?.active&&!paused,box=node('div',undefined,'queue-lane-control');box.append(node('span',(files?'Copy/delete: ':'')+running+' running · limit '+(state.queue_limits?.[kind]||(files?4:1)),'muted'));
 const control=button(active?'Ⅱ':'▶',async()=>{await api(active?'queue/pause':'run',{scope:'all',kind});await refresh();},'icon-button subtle');control.setAttribute('aria-label',(active?'Pause after current: ':'Start queue: ')+(files?'File operations':kind==='upscale'?'Upscaling':kind==='mage_generation'?'Artwork generation':kind==='metadata'?'Metadata':'Encoding')+' across all libraries');control.title=control.getAttribute('aria-label');control.disabled=!active&&!waiting;box.append(control);if(paused)box.append(node('span',running?'Pausing…':'Paused','muted'));return box;
}
function queueFileCard(job,head){
 const card=node('article',undefined,'processing-card queue-file-card '+(head?'queue-head':'queue-compact')),text=node('div',undefined,'processing-card-text');card.dataset.taskId=job.id;card.dataset.queueWaiting=String(job.phase==='waiting');
 const owner=state.tasks.find(t=>t.id===job.payload?.task),asset=catalogIndex().byId.get(owner?.asset);
 if(head&&asset)card.append(thumbnail(asset));
 if(job.phase==='waiting'&&Array.isArray(state.file_queue)){const check=node('input');check.type='checkbox';check.setAttribute('aria-label','Select waiting file operation '+job.title);check.checked=queueFileSelection.has(job.id);check.onchange=()=>{check.checked?queueFileSelection.add(job.id):queueFileSelection.delete(job.id);render();};check.disabled=queueChangeBusy;const drag=button('↕',()=>{},'subtle');drag.setAttribute('aria-label','Drag waiting file operation '+job.title);drag.disabled=queueChangeBusy;drag.style.touchAction='none';queueDrag(card,drag,job,true);card.append(check,drag);}
 text.append(button(job.title,()=>openQueueFile(job.id),'text-button task-name'),node('p',(state.libraries.find(l=>l.id===job.library)?.title||job.library||'People')+' · '+job.operation.replaceAll('_',' '),'muted'),node('p',job.phase==='waiting'?'Waiting':owner?.progress?'In progress':'In progress · progress unavailable','muted'));if(job.phase==='running'&&owner?.progress)text.append(progressView(owner));card.append(text,button('Details',()=>openQueueFile(job.id),'text-button'));return card;
}
function openQueueFile(id){
 const job=(state.file_jobs||[]).find(j=>j.id===id);if(!job||!prepareInspector())return;openedTask=id;inspectorMode='file-operation';$('task-kind').textContent='FILE OPERATION · '+job.phase.toUpperCase();$('task-title').textContent=job.title;$('task-reason').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren(node('p',job.operation.replaceAll('_',' ')+' · '+(state.libraries.find(l=>l.id===job.library)?.title||job.library)),node('p',job.phase==='waiting'?'Waiting for a shared file-operation slot.':'The operation is in progress. It cannot be moved or interrupted during a file commit.','muted'));actions.replaceChildren();if(job.error)detail.append(node('p',job.error,'error'));
 if(job.payload?.task)actions.append(button('View task',()=>openTask(job.payload.task),'text-button'));
 if(job.payload?.receipt)actions.append(button('View cleanup',async()=>openBackupCleanup(await api('cleanup?'+new URLSearchParams({id:job.payload.receipt}))),'text-button'));
 showInspector();
}
function renderQueueTaskFacts(detail,task,asset){
 const media=asset?.technical||{},settings={...task.plan,...task.tool_settings};
 detail.append(node('h3',task.status==='queued'?'Waiting to process':task.status==='publishing'?'Publishing':task.kind==='upscale'?'Upscaling in progress':'Encoding in progress'));
 if(asset)detail.append(thumbnail(asset,true));
 detail.append(node('h3','Source'),node('p',[media.width&&media.height?media.width+' × '+media.height:null,media.duration_seconds?Math.round(media.duration_seconds/60)+' min':null,formatBytes(task.source?.size??asset?.fingerprint?.size)].filter(Boolean).join(' · ')),node('p',asset?.plex_path||asset?.local_path||'Source path unavailable','muted'));
 detail.append(node('h3','Saved settings'));
 const values=[['handbrake_preset','Preset'],['topaz_filter','Upscale filter'],['topaz_rate_control','Output mode'],['topaz_quality','Quality'],['topaz_bitrate_mbps','Bitrate target (Mbps)']].filter(([key])=>settings[key]!==undefined&&settings[key]!==null&&settings[key]!=='');
 for(const [key,label] of values)detail.append(node('p',label+': '+settings[key]));
 if(!values.length)detail.append(node('p','No additional settings were recorded on this job.','muted'));
 if(task.status==='queued'){const position=node('p','','muted');position.dataset.queuePosition=task.id;detail.append(position,node('p','Removing this job returns it to suggestions. Saved settings, media and retained outputs are kept.','muted'));updateQueuePositions();}
}
function updateQueuePositions(){for(const label of document.querySelectorAll('[data-queue-position]')){const task=state.tasks.find(t=>t.id===label.dataset.queuePosition),ids=task?queueLaneIds(task.kind):[],position=ids.indexOf(task?.id);label.textContent=position<0?'Waiting status changed; reopen details before changing this job.':'Position '+(position+1)+' of '+ids.length+' in '+(task.kind==='upscale'?'Upscaling':task.kind==='mage_generation'?'Artwork generation':(TASK_LABELS[task.kind]||task.kind))+' across all libraries.';}}
function queueTaskDetailControls(task){
 const controls=node('div',undefined,'queue-lane-actions');
 for(const edge of ['top','bottom'])controls.append(button('Move to '+edge,()=>{const snapshot=waitingSnapshot().map(r=>({...r})),visible=queueVisibleIds(task.kind);if(!visible.includes(task.id))throw Error('Waiting job changed; refresh before moving it.');return changeWaitingQueue({order:mergeQueueOrder(snapshot.map(r=>r.id),visible,moveWaitingOrder(visible,new Set([task.id]),edge))},snapshot);},'text-button'));
 controls.append(button('Remove from queue',()=>taskAction(task,'remove_queue'),'text-button'));return controls;
}
function renderProcessing(){
 const typeCounts=new Map(),byId=new Map(state.tasks.map(t=>[t.id,t]));taskQueuePositions=new Map();for(const row of waitingSnapshot()){const task=byId.get(row.id);if(!task)continue;const position=(typeCounts.get(task.kind)||0)+1;typeCounts.set(task.kind,position);taskQueuePositions.set(task.id,position);}
 const board=node('div',undefined,'queue-board'),tasks=queueBoardTasks().filter(t=>queueVisible(t)&&(t.status!=='awaiting_review'||queueStatus==='awaiting_review'||!['upscale','optimize','join'].includes(t.kind))&&queueStatusMatches(t.status)),positions=new Map(waitingSnapshot().map((r,i)=>[r.id,i]));
 for(const [kind,title] of [['upscale','Upscaling'],['optimize','Encoding'],['file_operations','File operations'],['mage_generation','Artwork generation'],['metadata','Metadata']]){
  const metadataKinds=['metadata','folder_metadata','home'];
  const filePreparation=tasks.filter(t=>QUEUE_FILE_KINDS.has(t.kind)),orphans=queueOrphanCleanups().filter(r=>queueVisible({...r,title:'Clean up originals'})&&queueStatusMatches(r.phase==='queued'?'queued':r.phase==='deleting'?'publishing':'blocked'));
  const hasRows=kind==='file_operations'?queueActiveFiles().some(j=>queueVisible(j)&&queueStatusMatches(j.phase==='waiting'?'queued':'publishing'))||filePreparation.length||orphans.length:tasks.some(t=>t.kind===kind||(kind==='metadata'&&metadataKinds.includes(t.kind))||(kind==='mage_generation'&&t.kind==='artwork'&&t.provider));
  if(!hasRows)continue;
  const lane=node('section',undefined,'queue-lane'),header=node('div',undefined,'queue-lane-heading');lane.setAttribute('aria-label',title);header.append(node('h2',title),queueLaneControl(kind));lane.append(header,queueLaneSelection(kind));if(kind==='metadata')for(const subtype of ['home','folder_metadata'])if(tasks.some(t=>t.kind===subtype))lane.append(node('h3',TASK_LABELS[subtype]||subtype),taskQueueControls(subtype),queueLaneSelection(subtype));
  if(kind==='file_operations')for(const subtype of [...new Set(filePreparation.map(t=>t.kind))])lane.append(node('h3',(TASK_LABELS[subtype]||subtype)+' · preparation'),taskQueueControls(subtype),queueLaneSelection(subtype));
  const files=kind==='file_operations',rows=files?queueActiveFiles().filter(j=>queueVisible(j)&&queueStatusMatches(j.phase==='waiting'?'queued':'publishing')):tasks.filter(t=>t.kind===kind||(kind==='metadata'&&metadataKinds.includes(t.kind))||(kind==='mage_generation'&&t.kind==='artwork'&&t.provider)).sort((a,b)=>(a.status==='queued')-(b.status==='queued')||(positions.get(a.id)||0)-(positions.get(b.id)||0));
  const running=rows.filter(r=>files?r.phase==='running':['running','publishing'].includes(r.status)),waiting=rows.filter(r=>files?r.phase==='waiting':r.status==='queued'),attention=files?[]:rows.filter(r=>['failed','blocked'].includes(r.status));
  const head=running[0]||waiting[0],make=(row,head)=>{if(files)return queueFileCard(row,head);const card=processingTaskCard(row);card.dataset.queueWaiting=String(row.status==='queued');card.classList.add(head?'queue-head':'queue-compact');return card;};
  if(head)lane.append(make(head,true));else if(!files||!tasks.some(t=>QUEUE_FILE_KINDS.has(t.kind)))lane.append(node('p',rows.length?'No active jobs':'No jobs','queue-lane-empty muted'));
  for(const row of running.slice(1))lane.append(make(row,false));
  lane.append(node('h3',(files?'Copy/delete waiting (':'Waiting (')+waiting.length+')'));for(const row of waiting)if(row!==head)lane.append(make(row,false));
  for(const row of attention)lane.append(make(row,false));
  const review=files?[]:rows.filter(r=>r.status==='awaiting_review');if(review.length&&!['mage_generation','metadata'].includes(kind))lane.append(bulkTaskControls(review));for(const row of review)lane.append(make(row,false));
  if(files){
   const preparation=tasks.filter(t=>QUEUE_FILE_KINDS.has(t.kind)).sort((a,b)=>['running','publishing','queued','awaiting_review','failed','blocked'].indexOf(a.status)-['running','publishing','queued','awaiting_review','failed','blocked'].indexOf(b.status)||(positions.get(a.id)??0)-(positions.get(b.id)??0));let hasHead=Boolean(head);
   for(const kind of [...new Set(preparation.map(t=>t.kind))]){
    for(const task of preparation.filter(t=>t.kind===kind)){
     const card=processingTaskCard(task);card.dataset.queueWaiting=String(task.status==='queued');card.classList.add(hasHead?'queue-compact':'queue-head');lane.append(card);hasHead=true;
    }
   }
   const orphanIds=new Set(queueOrphanCleanups().filter(r=>queueVisible({...r,title:'Clean up originals'})&&queueStatusMatches(r.phase==='queued'?'queued':r.phase==='deleting'?'publishing':'blocked')).map(r=>r.id));
   for(const card of cleanupJobCards(false))if(orphanIds.has(card.dataset.cleanupId))lane.append(card);
  }
  foldWaitingQueue(lane,kind);board.append(lane);
 }
 const other=tasks.filter(t=>!['upscale','optimize','mage_generation','metadata','folder_metadata','home'].includes(t.kind)&&!(t.kind==='artwork'&&t.provider)&&!QUEUE_FILE_KINDS.has(t.kind)),extra=[];
 for(const kind of [...new Set(other.map(t=>t.kind))]){
  const section=node('section',undefined,'processing-group');section.append(node('h2',TASK_LABELS[kind]||kind),taskQueueControls(kind),queueLaneSelection(kind));
  section.append(...other.filter(t=>t.kind===kind).map(processingTaskCard));extra.push(section);
 }
 board.style.cssText='--queue-columns:'+Math.max(1,board.children.length);return board.children.length?[board,...extra]:extra;
}
