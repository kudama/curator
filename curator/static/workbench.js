'use strict';
// Navigation and presentation only. Editors continue to use the existing approved workflows.
const collapsedGroups=new Set(),fileRowCache=new Map();let overviewSignature='';
let queueLibrary='all';
let reviewKind='all',currentReviewSession=null,reviewAdvanceBusy=false;
let runStartBusy=false,notificationBaseline=false;const notifiedRuns=new Set();
function queueScope(){return Array.isArray(state.global_queue)?{scope:'all'}:{library:libraryId};}
function queueMatchesLibrary(task){return !Array.isArray(state.global_queue)?task.library===libraryId:queueLibrary==='all'||task.library===queueLibrary;}
let serviceRestarting=false,serviceStatus=null;
function serviceBusy(){return Boolean(state.queue_running||(state.cleanup_jobs||[]).some(j=>j.phase==='deleting')||(state.tasks||[]).some(t=>['running','publishing'].includes(t.status))||Object.values(state.scans||{}).some(s=>s.running)||Object.values(state.presence||{}).some(s=>s.running));}
function updateServiceControls(){
 const control=$('restart-curator'),note=$('service-status');if(!control||!note)return;
 control.disabled=serviceRestarting||!serviceStatus?.restart_available||serviceBusy();
 if(!serviceStatus)return;
 note.textContent=!serviceStatus.restart_available?'Restart is available when Curator runs as the managed service.':serviceBusy()?'Finish processing, publishing and library checks before restarting.':'Running on '+serviceStatus.hostname+(serviceStatus.startup==='boot'?'. Starts at boot after the startup disk is unlocked.':'. Starts after login.');
}
async function loadServiceStatus(){
 try{serviceStatus=await api('service/status');const build=serviceStatus.build,label=$('build-identity');if(label&&build){label.textContent='v'+build.version+' · '+(build.revision==='unknown'?'build unknown':build.revision.slice(0,8))+(build.dirty?' · modified':'');label.title='Running process started '+build.started_at+'; build '+build.revision;}updateServiceControls();updateFeatureControls();if(typeof render==='function')render();}
 catch(error){$('service-status').textContent='Service controls are unavailable in this running instance.';$('restart-curator').disabled=true;}
}
async function serviceFetch(path,options={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),3000);
 try{return await fetch(path,{...options,signal:controller.signal,cache:'no-store'});}
 finally{clearTimeout(timer);}
}
async function requestServiceRestart(){
 let response;
 try{response=await serviceFetch('/api/service/restart',{method:'POST',headers:{'Content-Type':'application/json','X-Curator-Request':'1'},body:'{}'});}
 catch(error){return;} // Acceptance may be uncertain: poll, never repeat the POST.
 if(response.status>=400&&response.status<500){
  let message='Restart was refused.';try{message=(await response.json()).error||message;}catch(error){}
  throw Error(message);
 }
}
async function waitForServiceRestart(instance,options={}){
 const now=options.now||Date.now,pause=options.pause||(ms=>new Promise(resolve=>setTimeout(resolve,ms))),deadline=now()+(options.timeout??60000);
 while(now()<deadline){
  await pause(1000);
  let status;
  try{
   const page=await serviceFetch('/');if(!page.ok)continue; // Renew the HttpOnly session cookie after restart.
   const response=await serviceFetch('/api/service/status');if(!response.ok)continue;status=await response.json();
  }catch(error){continue;}
  if(typeof status.instance_id==='string'&&status.instance_id!==instance)return status;
  if(status.restart_error)throw Error(status.restart_error);
 }
 throw Error('Curator has not reconnected yet. Check the service log before trying another restart.');
}
async function restartCurator(){
 if(serviceRestarting||serviceBusy())return;
 if(!confirm('Save any settings or review edits first. Restart Curator now? The page will reload.'))return;
 const note=$('service-restart-feedback');serviceRestarting=true;updateServiceControls();note.textContent='Requesting restart…';
 try{
  const before=await api('service/status');await requestServiceRestart();note.textContent='Waiting for Curator to reconnect…';
  await waitForServiceRestart(before.instance_id);location.reload();
 }catch(error){serviceRestarting=false;note.textContent=error.message;updateServiceControls();}
}
function inspectorOpen(){return !$('task-dialog').hidden;}
function prepareInspector(){
 const close=$('task-dialog').querySelector('[data-close]');
 if(close.disabled){toast('Wait for the current save to finish.',true);return false;}
 if(inspectorDirty&&!confirm('Discard unsaved changes in the review panel?'))return false;
 inspectorDirty=false;overviewSignature='';return true;
}
function showInspector(){$('task-dialog').hidden=false;updateQueueLayout();$('inspector-empty').hidden=true;const body=$('task-dialog').querySelector('.task-scroll');if(body)body.scrollTop=0;$('task-title').tabIndex=-1;$('task-title').focus({preventScroll:true});}
function closeInspector(force=false){if(!force&&!prepareInspector())return;inspectorDirty=false;openedTask=null;inspectorMode=null;$('task-dialog').hidden=true;$('inspector-empty').hidden=false;updateQueueLayout();document.querySelector('.workbench').classList.remove('review-wide');$('inspector-expand').setAttribute('aria-label','Expand review panel');$('inspector-expand').title='Expand review panel';document.querySelector('.file-entry[aria-pressed="true"]')?.focus({preventScroll:true});}
function fileName(asset){return (asset.plex_path||asset.local_path||'').split('/').pop()||asset.title;}
function matchesSearch(asset){return !searchText||[fileName(asset),asset.title,asset.plex_path].join(' ').toLocaleLowerCase().includes(searchText);}
function fileTasks(asset){if(!asset)return [];return (catalogIndex().byAsset.get(asset.id)||[]).filter(t=>t.library===libraryId);}
function attentionTasks(asset){return fileTasks(asset).filter(t=>['recommendation','blocked','failed','awaiting_review'].includes(t.status));}
function libraryFiles(){return state.assets.filter(a=>a.library===libraryId&&a.present!==false);}
function workspaceFiles(){return libraryFiles().filter(matchesSearch).filter(a=>screen!=='library'||libraryView==='files'||(libraryView==='completed'?movieCompleted(a):attentionTasks(a).length>0));}
function taskStatusLabel(status){return ({queued:'Waiting',running:'Processing',awaiting_review:'Ready to review'})[status]||String(status).replaceAll('_',' ');}
function fileBadge(asset){
 const tasks=fileTasks(asset);
 if(tasks.some(t=>t.status==='publishing'))return {text:'Publishing',kind:'running'};
 if(tasks.some(t=>t.status==='running'))return {text:'Processing',kind:'running'};
 if(tasks.some(t=>['blocked','failed'].includes(t.status)))return {text:'Needs attention',kind:'issue'};
 if(tasks.some(t=>t.status==='awaiting_review'))return {text:tasks.some(t=>['upscale','optimize','join'].includes(t.kind)&&t.status==='awaiting_review')?'Ready to publish':'Review suggestions',kind:'ready'};
 if(tasks.some(t=>t.status==='queued'))return {text:'Waiting',kind:'waiting'};
 const count=tasks.filter(t=>t.status==='recommendation').length;
 if(count)return {text:count+' '+(count===1?'suggestion':'suggestions'),kind:'attention'};
 return {text:movieCompleted(asset)?'Completed':'No pending work',kind:'complete'};
}
function thumbnail(asset,large=false){
 const box=node('div',undefined,'media-thumbnail'+(large?' large-thumb':'')),placeholder=node('span','▶');box.append(placeholder);
 if(asset?.present!==false&&asset?.item?.thumb){const img=node('img');img.alt='';img.loading='lazy';img.src='/api/assets/image?'+new URLSearchParams({asset:asset.id,v:asset.item.thumb});img.onerror=()=>img.remove();box.append(img);}
 return box;
}
function metaLine(asset){const media=asset.technical||{};const resolution=media.width&&media.height?media.width+' × '+media.height:null,duration=media.duration_seconds?Math.round(media.duration_seconds/60)+' min':null;return [resolution,duration].filter(Boolean).join(' · ')||asset.title||'Metadata available';}
function chooseLibrary(id){if(id!==libraryId&&!prepareInspector())return false;if(id!==libraryId){closeInspector(true);selectedAssetId=null;searchText='';$('file-search').value='';}libraryId=id;selected.clear();screen='library';render();run(syncCatalog);return true;}
function setScreen(value){if(screen!==value){searchText='';$('file-search').value='';}screen=value;filter=value==='processing'?'queued':value==='history'?'history':libraryView==='completed'?'completed':'all';selected.clear();render();}
function initThemeSelector(){
 const selector=document.getElementById('theme-selector');if(!selector)return;
 const apply=value=>{const theme=value==='cyberpunk'?'cyberpunk':'classic';document.documentElement.dataset.theme=theme;selector.value=theme;return theme;};
 let stored='classic';try{stored=localStorage.getItem('curator.theme')||stored;}catch(error){}
 apply(stored);
 selector.onchange=()=>{const theme=apply(selector.value);try{localStorage.setItem('curator.theme',theme);}catch(error){}};
}
function initWorkbench(){
 initThemeSelector();
 const batches=$('review-batches');if(batches)batches.onclick=()=>run(showReviewBatches);
 const cleanup=$('cleanup-backups');if(cleanup)cleanup.onclick=()=>run(showBackupCleanup);
 document.querySelectorAll('[data-screen]').forEach(b=>b.onclick=()=>setScreen(b.dataset.screen));
 $('inspector-expand').onclick=()=>{const wide=document.querySelector('.workbench').classList.toggle('review-wide');$('inspector-expand').setAttribute('aria-label',wide?'Restore review panel':'Expand review panel');$('inspector-expand').title=wide?'Restore review panel':'Expand review panel';};
 $('file-search').oninput=e=>{searchText=e.target.value.trim().toLocaleLowerCase();render();};
 $('collapse-folders').onclick=collapseAllFolders;
 $('queue-group').onchange=e=>{queueGrouping=e.target.value;render();};
 const queueLibraryControl=$('queue-library');if(queueLibraryControl)queueLibraryControl.onchange=e=>{queueLibrary=e.target.value;selected.clear();waitingSelection.clear();render();};
 const reviewKindControl=$('review-kind');if(reviewKindControl)reviewKindControl.onchange=e=>{reviewKind=e.target.value;selected.clear();render();};
 $('history-status').onchange=e=>{historyStatus=e.target.value;render();};
 const restart=$('restart-curator');if(restart)restart.onclick=restartCurator;
 window.addEventListener('beforeunload',e=>{if(inspectorDirty){e.preventDefault();e.returnValue='';}});
 $('task-detail').addEventListener('input',()=>{if(inspectorMode==='file-tools')inspectorDirty=true;});
 $('task-dialog').addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();closeInspector();}else handleReviewShortcut(e);});
}
function fileRow(asset,scope='files'){
 const id=scope+':'+asset.id,badge=fileBadge(asset),signature=JSON.stringify([fileName(asset),asset.title,asset.item?.thumb,metaLine(asset),badge,selectedAssetId===asset.id]);
 const cached=fileRowCache.get(id);if(cached?.signature===signature)return cached.row;
 const row=node('button',undefined,'file-entry'+(selectedAssetId===asset.id?' selected':''));row.type='button';row.setAttribute('aria-label',fileName(asset)+' · '+badge.text);row.setAttribute('aria-pressed',String(selectedAssetId===asset.id));
 const text=node('span',undefined,'file-entry-text');text.append(node('strong',fileName(asset)),node('span',metaLine(asset),'muted'));
 row.append(thumbnail(asset),text,node('span',badge.text,'file-badge '+badge.kind));row.onclick=()=>run(()=>openAssetOverview(asset.id));fileRowCache.set(id,{signature,row});return row;
}
function folderLabel(folder){const roots=(state.folders||[]).filter(f=>f.library===folder.library&&!f.parent),root=roots.filter(f=>folder.path===f.path||folder.path.startsWith(f.path.replace(/\/$/,'')+'/')).sort((a,b)=>b.path.length-a.path.length)[0];if(!root)return folder.path;const relative=folder.path.slice(root.path.length).replace(/^\//,'');const duplicate=roots.some(f=>f.id!==root.id&&f.name===root.name);return duplicate?folder.path:relative?(roots.length>1?root.name+' / ':'')+relative.split('/').join(' / '):root.name;}
function folderFor(asset){const path=asset.plex_path.split('/').slice(0,-1).join('/')||'/';return (state.folders||[]).find(f=>f.library===libraryId&&f.path===path);}
function rememberGroup(group,key){group.open=!collapsedGroups.has(key);group.ontoggle=()=>{group.open?collapsedGroups.delete(key):collapsedGroups.add(key);};return group;}
function collapseAllFolders(){
 if(screen!=='library'||!['folder','task'].includes(activeGrouping)||!libraryId)return;
 const prefix=libraryId+':'+activeGrouping+':';
 if(activeGrouping==='folder'){
  for(const folder of state.folders||[])if(folder.library===libraryId)collapsedGroups.add(prefix+folder.id);
  for(const asset of state.assets)if(asset.library===libraryId)collapsedGroups.add(prefix+asset.plex_path.split('/').slice(0,-1).join('/'));
 }else{
  for(const task of state.tasks||[])if(task.library===libraryId)collapsedGroups.add(prefix+task.kind);
  collapsedGroups.add(prefix+'other');
 }
 document.querySelectorAll('#tasks details.file-group').forEach(group=>{group.open=false;});
}
function renderFileList(files){
 if(activeGrouping==='movie')return files.map(a=>fileRow(a));
 const groups=new Map();
 if(activeGrouping==='folder'&&libraryView==='files'&&!searchText)for(const folder of (state.folders||[]).filter(f=>f.library===libraryId&&!f.parent))groups.set(folder.id,{id:folder.id,title:folderLabel(folder),folder,files:[]});
 for(const asset of files){const folder=folderFor(asset),kinds=activeGrouping==='task'?[...new Set(attentionTasks(asset).map(t=>t.kind))]:[];
  const keys=activeGrouping==='folder'?[{id:folder?.id||asset.plex_path.split('/').slice(0,-1).join('/'),title:folder?folderLabel(folder):'Other files',folder}]:kinds.length?kinds.map(kind=>({id:kind,title:TASK_LABELS[kind]||kind})):[{id:'other',title:'Other files'}];
  for(const key of keys){if(!groups.has(key.id))groups.set(key.id,{...key,files:[]});groups.get(key.id).files.push(asset);}
 }
 return [...groups.values()].map(group=>{const section=rememberGroup(node('details',undefined,'file-group collapsible-group'),libraryId+':'+activeGrouping+':'+group.id),head=node('summary',undefined,'file-group-heading');head.append(node('h3',(activeGrouping==='folder'?'▱  ':'')+group.title),node('span',String(group.files.length),'muted'));
  if(activeGrouping==='task'&&groupTaskRows(group).length)head.append(bulkTaskControls(groupTaskRows(group)));
  if(group.folder){const edit=button(group.folder.mapped===false?'Set Mac path':'Edit folder',()=>group.folder.mapped===false?openLibrarySettings():openFolder(group.folder.id),'subtle');edit.addEventListener('click',e=>{e.stopPropagation();e.preventDefault();});head.append(edit);}section.append(head,...group.files.map(a=>activeGrouping==='task'?selectableTaskFile(a,group):fileRow(a,group.id)));if(!group.files.length)section.append(node('p',group.folder?.mapped===false?'Set the Mac path to scan files in this location.':'No scanned files directly in this folder.','empty-folder-note'));return section;});
}
let historyStatus='all',queueGrouping='status',queueChangeBusy=false,queueDragging=false;const waitingSelection=new Set(),queueOpenMenus=new Set();let taskQueuePositions=new Map();
function waitingSnapshot(){return state.global_queue||state.queue_orders?.[libraryId]||state.tasks.filter(t=>t.library===libraryId&&t.status==='queued').map(t=>({id:t.id,version:t.version}));}
function processingTaskCard(task){
 const asset=catalogIndex().byId.get(task.asset),card=node('article',undefined,'processing-card'),main=node('div',undefined,'processing-card-main');
 if(task.status==='queued'){const check=node('input');check.type='checkbox';check.checked=waitingSelection.has(task.id);check.disabled=queueChangeBusy||!featureAvailable('queue_order');check.setAttribute('aria-label','Select waiting job '+(asset?fileName(asset):task.title));check.onchange=()=>{check.checked?waitingSelection.add(task.id):waitingSelection.delete(task.id);render();};main.append(check);const position=taskQueuePositions.get(task.id)||1;const textPosition=node('span',(TASK_LABELS[task.kind]||task.kind)+' #'+position,'muted');main.append(textPosition);if(featureAvailable('queue_order')){card.dataset.waitingId=task.id;card.title='Drag the arrow handle onto another waiting job to move before it';const handle=button('↕',()=>{},'subtle');handle.setAttribute('aria-label','Drag waiting job '+(asset?fileName(asset):task.title));handle.style.touchAction='none';handle.disabled=queueChangeBusy;main.append(handle);let origin=null;
 handle.onpointerdown=e=>{if(queueChangeBusy)return;e.preventDefault();origin=[e.clientX,e.clientY];queueDragging=true;handle.setPointerCapture(e.pointerId);};
 handle.onpointerup=e=>{if(!origin)return;const moved=Math.hypot(e.clientX-origin[0],e.clientY-origin[1])>5;origin=null;queueDragging=false;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-waiting-id]')?.dataset.waitingId;const order=moved?dropWaitingOrder(waitingSnapshot().map(r=>r.id),task.id,target):null;if(order)run(()=>changeWaitingQueue({order}));else render();};
 handle.onpointercancel=()=>{origin=null;queueDragging=false;render();};}}

 if(task.status==='awaiting_review'&&['upscale','optimize'].includes(task.kind)){const check=node('input');check.type='checkbox';check.checked=selected.has(task.id);check.setAttribute('aria-label','Select '+(asset?fileName(asset):task.title));check.onchange=()=>{selectTaskRows([task],check.checked);render();};main.append(check);}
 main.append(thumbnail(asset||{}));const text=node('div',undefined,'processing-card-text');text.append(node('strong',asset?fileName(asset):task.title),node('p',(TASK_LABELS[task.kind]||task.kind)+' · '+(task.cancel_requested?'Cancelling…':taskStatusLabel(task.status)),'muted'));
 if(Array.isArray(state.global_queue))text.append(node('p',state.libraries.find(lib=>lib.id===task.library)?.title||task.library,'muted'));if(task.error)text.append(node('p',task.error,'task-error'));if(task.recovery_hint)text.append(node('p',task.recovery_hint,'muted'));if(['running','publishing'].includes(task.status))text.append(progressView(task));
 if(task.status==='awaiting_review'&&task.result?.size_bytes)text.append(node('p',formatBytes(task.source?.size??asset?.fingerprint?.size)+' → '+formatBytes(task.result.size_bytes),'muted'));
 main.append(text);const actions=node('div',undefined,'processing-card-actions');actions.append(button(task.status==='awaiting_review'?(['upscale','optimize','join'].includes(task.kind)?'Compare & publish':'Review suggestions'):['blocked','failed'].includes(task.status)?'Inspect':'Details',()=>openTask(task.id),task.status==='awaiting_review'?'primary':'subtle'));const more=queueActionMenu('job:'+task.id,'queue-job-more');more.append(node('summary','More'));more.append(taskControls(task));actions.append(more);main.append(actions);card.append(main);return card;
}
function renderProcessing(){
 const snapshot=waitingSnapshot(),positions=new Map(snapshot.map((r,i)=>[r.id,i])),byId=new Map(state.tasks.map(t=>[t.id,t])),typeCounts=new Map();taskQueuePositions=new Map();for(const row of snapshot){const kind=byId.get(row.id)?.kind,index=(typeCounts.get(kind)||0)+1;typeCounts.set(kind,index);taskQueuePositions.set(row.id,index);}
 const tasks=state.tasks.filter(t=>queueMatchesLibrary(t)&&['queued','running','publishing','awaiting_review','failed','blocked'].includes(t.status)&&(queueStatus==='all'||(queueStatus==='attention'?['failed','blocked'].includes(t.status):queueStatus==='running'?['running','publishing'].includes(t.status):t.status===queueStatus))&&(!searchText||[t.title,catalogIndex().byId.get(t.asset)?.plex_path,TASK_LABELS[t.kind]].join(' ').toLowerCase().includes(searchText))).sort((a,b)=>['publishing','running','queued','awaiting_review','failed','blocked'].indexOf(a.status)-['publishing','running','queued','awaiting_review','failed','blocked'].indexOf(b.status)||(positions.get(a.id)??0)-(positions.get(b.id)??0));
 const groups=[['Publishing',['publishing']],['Processing',['running']],['Waiting',['queued']],['Ready to publish / review',['awaiting_review']],['Needs attention',['failed','blocked']]];
 const sections=queueGrouping==='task'?[...new Set(tasks.map(t=>t.kind))].map(kind=>[TASK_LABELS[kind]||kind,null,kind]):groups;
 return [...fileOperationCards(),...cleanupJobCards(false),...sections.flatMap(([title,statuses,kind])=>{const rows=tasks.filter(t=>kind?t.kind===kind:statuses.includes(t.status));if(!rows.length)return [];const section=rememberGroup(node('details',undefined,'processing-group collapsible-group'),libraryId+':processing:'+title),heading=node('summary',undefined,'processing-group-heading');heading.append(node('h2',title+' ('+rows.length+')'));if(kind&&rows.some(t=>['queued','running','publishing'].includes(t.status)))heading.append(taskQueueControls(kind));const waiting=rows.filter(t=>t.status==='queued');if(waiting.length)heading.append(waitingGroupControls(waiting));const review=rows.filter(t=>t.status==='awaiting_review'&&['upscale','optimize'].includes(t.kind));if(review.length)heading.append(bulkTaskControls(review));section.append(heading,...rows.map(processingTaskCard));return [section];})];
}
function fileOperationCards(){
 const jobs=(state.file_jobs||[]).filter(j=>['waiting','running'].includes(j.phase)&&queueMatchesLibrary(j));if(!jobs.length)return [];
 const section=node('section',undefined,'processing-group'),running=(state.file_jobs||[]).filter(j=>j.phase==='running').length;
 section.append(node('h2','File copy / delete · '+running+' running · shared limit '+(state.queue_limits?.file_operations||4)));
 section.append(button('Resume file operations',()=>run(async()=>{await api('run',{scope:'all',kind:'file_operations'});await refresh();}),'subtle'),button('Pause after current',()=>run(async()=>{await api('queue/pause',{scope:'all',kind:'file_operations'});await refresh();}),'subtle'));
 for(const job of jobs){const card=node('article',undefined,'processing-card');card.append(node('strong',job.title),node('p',job.operation.replaceAll('_',' ')+' · '+(job.phase==='waiting'?'Waiting for file operation slot':'Running')+' · '+(state.libraries.find(lib=>lib.id===job.library)?.title||job.library),'muted'));section.append(card);}
 return [section];
}
function reviewInboxRows(){return state.tasks.filter(t=>t.status==='awaiting_review'&&['upscale','optimize','join'].includes(t.kind)&&queueMatchesLibrary(t)&&(reviewKind==='all'||t.kind===reviewKind)&&(!searchText||[t.title,catalogIndex().byId.get(t.asset)?.plex_path].join(' ').toLocaleLowerCase().includes(searchText)));}
function savedReviewSessionId(){try{return localStorage.getItem('curator.review-session');}catch(error){return currentReviewSession?.id;}}
function renderReviewInbox(){
 const rows=reviewInboxRows(),controls=node('div',undefined,'bulk-group-actions');
 if(featureAvailable('continuous_review')){
  const start=button('Start reviewing',()=>run(()=>startContinuousReview(false)),'primary');start.disabled=!rows.some(t=>['upscale','optimize'].includes(t.kind))||reviewAdvanceBusy;controls.append(start);
  if(savedReviewSessionId())controls.append(button('Resume review',()=>run(()=>startContinuousReview(true)),'subtle'));
 }
 if(rows.length)controls.append(bulkTaskControls(rows.filter(t=>['upscale','optimize'].includes(t.kind))));
 return [controls,...rows.map(processingTaskCard)];
}
async function startContinuousReview(resume){
 if(reviewAdvanceBusy||!prepareInspector())return;reviewAdvanceBusy=true;
 try{
  const payload=resume?{id:savedReviewSessionId()}:{library:queueLibrary==='all'?null:queueLibrary,kind:reviewKind==='all'||reviewKind==='join'?null:reviewKind,tasks:reviewInboxRows().filter(t=>['upscale','optimize'].includes(t.kind)).slice(0,5000).map(t=>({id:t.id,version:t.version}))};
  if(resume&&!payload.id)return;
  currentReviewSession=await api('review-session/open',payload);
  try{localStorage.setItem('curator.review-session',currentReviewSession.id);}catch(error){}
  await openNextReviewResult();
 }finally{reviewAdvanceBusy=false;}
}
function continuousReviewTask(id){return currentReviewSession?.items[currentReviewSession.cursor]?.id===id;}
async function openNextReviewResult(){
 const item=currentReviewSession?.items[currentReviewSession.cursor];
 if(!item){closeInspector(true);setScreen('review');const counts={};for(const row of currentReviewSession?.items||[])counts[row.decision]=(counts[row.decision]||0)+1;toast('Review session finished · '+Object.entries(counts).map(([key,count])=>count+' '+key).join(' · ')+'. Accepted results may still be publishing.');return;}
 Promise.resolve(openTask(item.id)).catch(error=>{if(openedTask===item.id)toast('Could not open review: '+error.message,true);});
}
async function afterReviewDecision(id,decision,advance=true){
 if(!continuousReviewTask(id)||reviewAdvanceBusy)return;reviewAdvanceBusy=true;
 try{
  try{currentReviewSession=await api('review-session/step',{id:currentReviewSession.id,version:currentReviewSession.version,task:id,decision});}
  catch(error){currentReviewSession=await api('review-session/open',{id:currentReviewSession.id});toast('Review position reconciled with the task status.');}
  if(advance)await openNextReviewResult();
 }catch(error){toast('Decision saved on the task; resume review to recover the position. '+error.message,true);}
 finally{reviewAdvanceBusy=false;}
}
function decorateContinuousReview(task,actions){
 if(!continuousReviewTask(task.id))return;
 $('task-kind').textContent+=' · '+(currentReviewSession.cursor+1)+' of '+currentReviewSession.items.length;
 for(const control of actions.querySelectorAll('button')){
  if(control.textContent==='Accept & publish')control.setAttribute('data-review-action','accepted');
  if(control.textContent==='Reject result')control.setAttribute('data-review-action','rejected');
 }
 const skip=button('Skip / Next',()=>run(()=>afterReviewDecision(task.id,'skipped')),'subtle');skip.setAttribute('data-review-action','skipped');actions.append(skip);
 $('task-detail').append(node('p','A: accept and publish · R: reject and reset · S: skip. Your review position is saved.','muted'));
}
function handleReviewShortcut(event){
 if(reviewAdvanceBusy||!continuousReviewTask(openedTask)||event.repeat||event.ctrlKey||event.metaKey||event.altKey||event.target?.closest('input,textarea,select,[contenteditable="true"]'))return;
 const decision={a:'accepted',r:'rejected',s:'skipped'}[event.key.toLowerCase()];if(!decision)return;
 const control=$('task-buttons').querySelector('[data-review-action="'+decision+'"]');if(!control||control.disabled)return;
 event.preventDefault();control.click();
}
function cleanupJobCards(history){
 return (state.cleanup_jobs||[]).filter(j=>(history?j.library===libraryId:queueMatchesLibrary(j))&&(history?(j.phase==='complete'||j.phase==='interrupted')&&historyStatusMatches({status:j.phase==='interrupted'?'blocked':j.failed?'failed':'applied'}):j.phase!=='complete')).map(job=>{
  const card=node('article',undefined,'processing-card'),text=node('div',undefined,'processing-card-text');
  text.append(node('strong','Clean up originals'),node('p',(job.phase==='queued'?'Waiting for file operation slot':job.phase==='deleting'?'Processing':job.phase==='complete'?(job.failed?'Finished with failures':'Completed'):'Interrupted')+' · '+job.completed+' of '+job.total+' checked · '+job.deleted+' deleted · '+job.failed+' failed','muted'));
  if(job.phase==='deleting'&&job.current)text.append(node('p',job.current.phase+' · '+job.current.title,'muted'));
  const progress=node('progress');progress.max=job.total||1;progress.value=job.completed;text.append(progress);
  card.append(text,button('Details',async()=>{if(!prepareInspector())return;openBackupCleanup(await api('cleanup?'+new URLSearchParams({id:job.id})));},'subtle'));return card;
 });
}
function moveWaitingOrder(ids,chosen,edge){
 const selected=ids.filter(id=>chosen.has(id)),rest=ids.filter(id=>!chosen.has(id));
 return edge==='top'?[...selected,...rest]:[...rest,...selected];
}
function waitingGroupControls(rows){
 const controls=node('div',undefined,'bulk-group-actions'),all=rows.every(t=>waitingSelection.has(t.id));
 const select=button(all?'Clear waiting selection':'Select waiting ('+rows.length+')',()=>{for(const task of rows)all?waitingSelection.delete(task.id):waitingSelection.add(task.id);render();},'subtle');
 select.disabled=queueChangeBusy||!featureAvailable('queue_order');select.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();});controls.append(select);return controls;
}
function dropWaitingOrder(ids,id,target){
 if(id===target||!ids.includes(id)||!ids.includes(target))return null;
 const order=ids.filter(key=>key!==id);order.splice(order.indexOf(target),0,id);return order;
}
async function changeWaitingQueue(change){
 if(queueChangeBusy)return;
 const expected=waitingSnapshot().map(r=>({...r}));queueChangeBusy=true;render();
 try{await api('queue/change',{...queueScope(),expected,...change});waitingSelection.clear();if(change.remove)toast(change.remove.length+' returned to suggestions. Saved settings are retained.');}
 finally{queueChangeBusy=false;await refresh();}
}
function queueActionMenu(key,cls){const menu=node('details',undefined,cls);menu.open=queueOpenMenus.has(key);menu.ontoggle=()=>{menu.open?queueOpenMenus.add(key):queueOpenMenus.delete(key);};return menu;}
function renderWaitingControls(){
 const container=$('queue-actions');if(!container)return;container.hidden=screen!=='processing';container.replaceChildren();if(container.hidden)return;
 const ids=waitingSnapshot().map(r=>r.id),available=new Set(ids);for(const id of waitingSelection)if(!available.has(id))waitingSelection.delete(id);
 const visibleIds=ids.filter(id=>queueMatchesLibrary(state.tasks.find(t=>t.id===id)||{}));
 const enabled=featureAvailable('queue_order')&&!queueChangeBusy;
 if(featureAvailable('task_queues')&&(state.tasks.some(t=>['running','publishing'].includes(t.status))||(state.file_jobs||[]).some(j=>j.phase==='running')))container.append(button('Pause after current',()=>run(async()=>{await api('queue/pause',queueScope());await refresh();toast('Queues will pause after their current jobs finish.');}),'subtle'));
 if(Array.isArray(state.global_queue))container.append(button('Processing limits',showQueueLimits,'subtle'));
 if(featureAvailable('unattended_runs')){
  const failed=state.tasks.filter(t=>queueMatchesLibrary(t)&&safeFailedRetry(t));
  const retry=button('Retry failed jobs ('+failed.length+')',()=>run(async()=>{retry.disabled=true;try{const result=await api('recovery/retry-failed',{tasks:failed.slice(0,5000).map(t=>({id:t.id,version:t.version}))});await refresh();toast(result.queued+' requeued; inspect other failures, then Run when ready.');}finally{retry.disabled=false;}}),'subtle');retry.disabled=!failed.length;if(failed.length)container.append(retry);
 }
 const add=(label,fn,disabled=false)=>{const control=button(label,()=>run(fn),'subtle');control.disabled=!enabled||disabled;container.append(control);};
 if(visibleIds.length)add(waitingSelection.size===visibleIds.length&&visibleIds.length?'Clear waiting selection':'Select all waiting ('+visibleIds.length+')',()=>{const clear=waitingSelection.size===visibleIds.length;waitingSelection.clear();if(!clear)for(const id of visibleIds)waitingSelection.add(id);render();},!visibleIds.length);
 if(waitingSelection.size)for(const edge of ['top','bottom'])add('Move selected to '+edge,()=>changeWaitingQueue({order:moveWaitingOrder(ids,waitingSelection,edge)}),!waitingSelection.size);
 if(waitingSelection.size)add('Remove selected ('+waitingSelection.size+')',()=>{const remove=ids.filter(id=>waitingSelection.has(id));if(confirm('Return '+remove.length+' waiting jobs to suggestions? Saved settings, media and outputs stay unchanged.'))return changeWaitingQueue({remove});},!waitingSelection.size);
 if(ids.length){const more=queueActionMenu('waiting','queue-more');more.append(node('summary','More'));const menu=node('div');container.append(more);more.append(menu);
 const empty=button('Return all waiting jobs to suggestions',()=>run(()=>{if(confirm('Return all '+ids.length+' waiting jobs '+(Array.isArray(state.global_queue)?'across all libraries':'in this library')+' to suggestions? Running jobs, media and outputs stay unchanged.'))return changeWaitingQueue({remove:ids});}),'subtle');empty.disabled=!enabled;menu.append(empty);}
 if(!featureAvailable('queue_order'))container.append(node('span','Reordering becomes available after the idle backend update.','muted'));
}
function safeFailedRetry(task){return ['blocked','failed'].includes(task.status)&&['upscale','optimize','home','metadata'].includes(task.kind)&&!task.deleted&&!['output','published','publication_error','rename_started','file_move_pending','cleanup_pending','provider'].some(key=>task[key]);}
async function showRunReadiness(){
 if(runStartBusy||!prepareInspector())return;runStartBusy=true;
 inspectorMode='run-readiness';openedTask=null;$('task-kind').textContent='UNATTENDED PROCESSING';$('task-title').textContent='Ready to leave running?';$('task-reason').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren(node('p','Checking queued sources, tools and storage…','muted'));actions.replaceChildren();showInspector();
 try{
  const snapshot=await api('run/readiness',queueScope());if(inspectorMode!=='run-readiness')return;
  detail.replaceChildren(node('p',snapshot.waiting+' waiting · '+snapshot.running+' processing · '+snapshot.file_waiting+' file operations waiting'));
  detail.append(node('p','Shared limits: '+Object.entries({upscale:1,optimize:1,file_operations:4,...snapshot.limits}).map(([kind,count])=>(kind==='file_operations'?'File copy / delete':TASK_LABELS[kind]||kind)+': '+count).join(' · '),'muted'));
  detail.append(node('p',snapshot.processing_eta_seconds==null?'Processing estimate unavailable until comparable jobs have been measured.':'Approximate processing time: '+formatRunDuration(snapshot.processing_eta_seconds),'muted'),node('p',snapshot.estimate_note,'muted'));
  for(const volume of snapshot.volumes)detail.append(node('p',volume.locations.join(' / ')+': '+formatBytes(volume.free_bytes)+' free · '+formatBytes(volume.estimated_extra_bytes)+' estimated extra'+(volume.unknown_jobs?' · '+volume.unknown_jobs+' output-size estimates unknown':'')+(volume.low_space?' · LOW SPACE':''),volume.low_space?'error':'muted'));
  if(snapshot.issues.length){detail.append(node('h3',snapshot.issues.length+' jobs or locations need attention'));for(const issue of snapshot.issues.slice(0,20))detail.append(node('p',(issue.title?issue.title+': ':'')+issue.message,'error'));detail.append(node('p','Affected jobs are checked again and held if unavailable; unrelated eligible work can continue.','muted'));}
  const start=button('Start unattended run',()=>run(async()=>{if(start.disabled)return;start.disabled=true;try{await api('run',queueScope());closeInspector(true);await refresh();toast('Run started with shared limits. Its summary remains in Queue.');}catch(error){start.disabled=false;throw error;}}),'primary');start.disabled=!snapshot.waiting&&!snapshot.file_waiting;actions.append(start);
 }catch(error){if(inspectorMode==='run-readiness'){detail.replaceChildren(node('p','Could not check readiness: '+error.message,'error'));actions.append(button('Retry checks',()=>run(showRunReadiness),'subtle'));}}
 finally{runStartBusy=false;}
}
function formatRunDuration(seconds){const minutes=Math.max(1,Math.round(seconds/60));return minutes<60?minutes+' min':Math.floor(minutes/60)+' hr '+minutes%60+' min';}
function summaryText(summary){const labels={ready:'ready for review',published:'published',accepted:'accepted / publishing',completed:'completed',failed:'failed or blocked',remaining:'remaining',changed:'changed',cancelled:'cancelled',reset:'reset',deleted:'deleted'};return Object.entries(labels).filter(([key])=>summary.counts[key]).map(([key,label])=>summary.counts[key]+' '+label).join(' · ')||'No remaining work';}
function renderRunSummaries(){
 const container=$('run-summaries');if(!container)return;const summaries=state.run_summaries||[];
 container.hidden=screen!=='processing'||!featureAvailable('unattended_runs')||!summaries.length;
 const signature=JSON.stringify(summaries);if(container.dataset.signature!==signature){
  container.dataset.signature=signature;container.replaceChildren();
  const details=node('details',undefined,'queue-activity'),heading=node('summary','Recent activity ('+summaries.length+')');details.append(heading);
  for(const summary of summaries.slice(0,5)){
   const row=node('section',undefined,'queue-activity-row'),text=node('div');
   text.append(node('strong',summary.title),node('p',summaryText(summary),'muted'));
   row.append(text,node('span',summary.phase.replaceAll('_',' '),'queue-state'));
   details.append(row);
  }
  container.append(details);
 }
 if(Array.isArray(state.run_summaries))notifyRunChanges(summaries);
}
function updateNotificationSettings(){
 const control=$('enable-run-notifications'),note=$('run-notification-note');if(!control||!note)return;
 const supported=typeof Notification!=='undefined'&&window.isSecureContext;
 control.hidden=!supported;note.textContent=supported?'Optional batch completion alerts while this browser stays open.':'Browser alerts are unavailable on this connection. Batch results are saved in Queue’s recent activity.';
 control.onclick=()=>run(enableRunNotifications);
}
function renderQueueStatusTabs(){
 const container=$('queue-status-tabs');if(!container)return;container.hidden=screen!=='processing';container.replaceChildren();if(container.hidden)return;
 const tasks=state.tasks.filter(queueMatchesLibrary),groups=[['all','All jobs',null],['running','Processing',['running','publishing']],['queued','Waiting',['queued']],['awaiting_review','Ready to review',['awaiting_review']],['attention','Needs attention',['blocked','failed']]];
 for(const [value,label,statuses] of groups){
  const count=tasks.filter(t=>(statuses||['running','publishing','queued','awaiting_review','blocked','failed']).includes(t.status)).length;
  const control=button(label+' '+count,()=>{queueStatus=value;render();},queueStatus===value?'active':'subtle');control.setAttribute('aria-pressed',String(queueStatus===value));container.append(control);
 }
}
function updateQueueLayout(){
 const bench=document.querySelector('.workbench');bench.classList.toggle('queue-workspace',screen==='processing');bench.classList.toggle('queue-inspecting',screen==='processing'&&inspectorOpen());
 document.querySelector('main').classList.toggle('queue-page',screen==='processing');
}
function notifyRunChanges(summaries){
 if(!notificationBaseline){try{for(const id of JSON.parse(localStorage.getItem('curator.notified-runs')||'[]'))notifiedRuns.add(id);}catch(error){}for(const summary of summaries)if(['complete','needs_attention','interrupted'].includes(summary.phase))notifiedRuns.add(summary.id);notificationBaseline=true;return;}
 for(const summary of summaries){
  if(!['complete','needs_attention','interrupted'].includes(summary.phase)||notifiedRuns.has(summary.id))continue;
  notifiedRuns.add(summary.id);
  try{if(localStorage.getItem('curator.run-notifications')==='enabled'&&typeof Notification!=='undefined'&&Notification.permission==='granted'){
   const otherWork=(state.tasks||[]).some(t=>['queued','running','publishing'].includes(t.status))||(state.file_jobs||[]).some(j=>['waiting','running'].includes(j.phase));
   const notification=new Notification(summary.phase==='complete'?'Curator batch finished':'Curator needs attention',{body:summaryText(summary)+(otherWork?'. Processing or publication remains in Queue.':''),tag:summary.id});notification.onclick=()=>{window.focus();queueLibrary='all';setScreen(summary.counts.ready?'review':'processing');};
  }}catch(error){}
 }
 try{localStorage.setItem('curator.notified-runs',JSON.stringify([...notifiedRuns].slice(-1000)));}catch(error){}
}
async function enableRunNotifications(){
 if(typeof Notification==='undefined'||!window.isSecureContext){toast('Browser notifications are unavailable here. Durable summaries remain in Queue.');return;}
 const permission=await Notification.requestPermission();
 try{localStorage.setItem('curator.run-notifications',permission==='granted'?'enabled':'disabled');}catch(error){}
 toast(permission==='granted'?'Run notifications enabled while this browser is open.':'Notifications were not enabled. Run summaries remain in Queue.');
}
function renderHistory(){
 return [...cleanupJobCards(true),...state.tasks.filter(t=>t.library===libraryId&&historyStatusMatches(t)&&(!searchText||[t.title,catalogIndex().byId.get(t.asset)?.plex_path,TASK_LABELS[t.kind]].join(' ').toLowerCase().includes(searchText))).sort((a,b)=>(b.updated||'').localeCompare(a.updated||'')).map(task=>{const row=node('article',undefined,'history-row'),text=node('div');text.append(node('strong',catalogIndex().byId.get(task.asset)?fileName(catalogIndex().byId.get(task.asset)):task.title),node('p',(TASK_LABELS[task.kind]||task.kind)+' · '+taskStatusLabel(task.status)+' · '+new Date(task.updated||task.created).toLocaleString(),'muted'));row.append(text,button('View',()=>openTask(task.id),'subtle'),taskControls(task));return row;})];
}
function historyStatusMatches(task){
 const allowed=['applied','resolved','cancelled','rejected','failed','blocked'];
 if(!allowed.includes(task.status))return false;
 return historyStatus==='all'||(historyStatus==='completed'?['applied','resolved'].includes(task.status):task.status===historyStatus);
}
function taskQueueControls(kind){
 const box=node('div',undefined,'bulk-group-actions'),info=(state.task_queues||[]).find(q=>(q.library===null||q.library===libraryId)&&q.kind===kind);
 if(!featureAvailable('task_queues'))return box;
 const start=button(info?.paused?'Resume queue':'Run queue',async()=>{const result=await api('run',{...queueScope(),kind});await refresh();toast(result.busy?.length?'This task type is running in another library.':'Task-type queue running.');},'subtle');
 start.disabled=!info?.waiting||info?.busy_elsewhere||Boolean(info?.active&&!info?.paused);
 const pause=button(info?.paused?(info.active?'Pausing after current…':'Paused'):'Pause after current',async()=>{await api('queue/pause',{...queueScope(),kind});await refresh();},'subtle');pause.disabled=!info||info.paused;
 if(info?.limit)box.append(node('span',info.running+' running · limit '+info.limit,'muted'));
 box.append(start,pause);if(info?.waiting_for_retry)box.append(node('span','Waiting for temporary file-access retry','muted'));if(info?.waiting_for_source)box.append(node('span','Waiting for another job on this file','muted'));
 for(const control of box.querySelectorAll('button'))control.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();});return box;
}
function showQueueLimits(){
 if(!prepareInspector())return;inspectorMode='queue-limits';openedTask=null;$('task-kind').textContent='PROCESSING';$('task-title').textContent='Shared processing limits';$('task-reason').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();
 detail.append(node('p','Limits apply across all libraries. Lowering a limit lets current jobs finish. Run or Resume fills additional slots after an increase.','muted'));
 const inputs=new Map(),kinds=new Set(['upscale','optimize','file_operations',...state.tasks.filter(t=>t.status==='queued'||t.status==='running').map(t=>t.kind)]);
 for(const kind of kinds){const label=node('label',kind==='file_operations'?'File copy / delete':TASK_LABELS[kind]||kind),input=node('input');input.type='number';input.min=1;input.max=kind==='file_operations'?4:8;input.step=1;input.value=state.queue_limits?.[kind]||(kind==='file_operations'?4:1);label.append(input);detail.append(label);inputs.set(kind,input);}
 actions.append(button('Save limits',()=>run(async()=>{const limits=Object.fromEntries([...inputs].map(([kind,input])=>[kind,Number(input.value)]));await api('queue/limits',{limits});closeInspector(true);await refresh();toast('Shared processing limits saved.');}),'primary'));showInspector();
}
function renderWorkbench(){
 if(queueDragging)return;
 if(typeof pruneGroupSelection==='function')pruneGroupSelection();
 const cleanupControl=$('cleanup-backups');if(cleanupControl){cleanupControl.hidden=screen!=='library';cleanupControl.disabled=!featureAvailable('backup_cleanup');cleanupControl.title=featureAvailable('backup_cleanup')?'Preview retained original backups':'Available after the pending backend update';}
 const batchControl=$('review-batches');if(batchControl){batchControl.hidden=screen==='processing';batchControl.disabled=!featureAvailable('bulk_review');batchControl.title=featureAvailable('bulk_review')?'Saved batch reviews':'Available after the pending backend update';}
 $('libraries').replaceChildren(...state.libraries.map(lib=>button(lib.title,()=>chooseLibrary(lib.id),lib.id===libraryId?'selected':'')));
 const queueFilter=$('queue-library');if(queueFilter){$('queue-library-control').hidden=!['processing','review'].includes(screen)||!Array.isArray(state.global_queue);const signature=JSON.stringify(state.libraries.map(lib=>[lib.id,lib.title]));if(queueFilter.dataset.libraries!==signature){queueFilter.replaceChildren();for(const lib of [{id:'all',title:'All libraries'},...state.libraries]){const option=node('option',lib.title);option.value=lib.id;queueFilter.append(option);}queueFilter.dataset.libraries=signature;}if(!state.libraries.some(lib=>lib.id===queueLibrary))queueLibrary='all';queueFilter.value=queueLibrary;}
 document.querySelectorAll('[data-screen]').forEach(b=>b.classList.toggle('active',b.dataset.screen===screen));
 const searchLabel=screen==='library'?'Search files in this library':screen==='review'?'Search review results':screen==='processing'?'Search jobs':'Search history';$('file-search').setAttribute('aria-label',searchLabel);$('file-search').placeholder=searchLabel;
 updateQueueLayout();renderQueueStatusTabs();renderRunSummaries();
 const lib=current(),assets=libraryFiles(),tasks=state.tasks.filter(t=>['processing','review'].includes(screen)?queueMatchesLibrary(t):t.library===libraryId),running=tasks.filter(t=>t.status==='running'),publishing=tasks.filter(t=>t.status==='publishing'),waiting=tasks.filter(t=>t.status==='queued'),ready=tasks.filter(t=>t.status==='awaiting_review');
 $('library-title').textContent=screen==='library'?(lib?.title||'Your library'):screen==='processing'?'Queue':screen==='review'?'Ready for review':'History';$('library-type').textContent=screen==='library'?(lib?.profile==='home'?'HOME MOVIES':'TV & MOVIES'):['processing','review'].includes(screen)&&Array.isArray(state.global_queue)?(queueLibrary==='all'?'ALL LIBRARIES':state.libraries.find(row=>row.id===queueLibrary)?.title||'ALL LIBRARIES'):(lib?.title||'WORKSPACE');
 $('library-note').textContent=screen==='library'?'Review what needs attention, one file at a time.':screen==='review'?'Compare processed results across libraries, then accept, reject or skip.':screen==='processing'?running.length+' processing · '+publishing.length+' publishing · '+waiting.length+' waiting · '+ready.length+' ready to review':'Completed, cancelled and resolved work. Media files stay in your library.';
 $('asset-count').textContent=assets.length;$('attention-count').textContent=assets.filter(a=>attentionTasks(a).length).length;$('completed-count').textContent=assets.filter(movieCompleted).length;
 $('finding-count').textContent=tasks.filter(t=>t.status==='recommendation').length;$('queue-count').textContent=running.length+waiting.length;$('review-count').textContent=ready.length;$('nav-processing-count').textContent=running.length+publishing.length+waiting.length+ready.length+(state.cleanup_jobs||[]).filter(j=>j.library===libraryId&&j.phase==='deleting').length||'';
 const reviewNav=$('nav-review');if(reviewNav){reviewNav.hidden=!featureAvailable('continuous_review');$('nav-review-count').textContent=state.tasks.filter(t=>t.status==='awaiting_review'&&['upscale','optimize','join'].includes(t.kind)).length||'';$('review-kind-control').hidden=screen!=='review';$('review-kind').value=reviewKind;}
 $('filters').hidden=screen!=='library';document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===libraryView));
 $('group-by-control').hidden=screen!=='library';$('group-by').value=activeGrouping;$('history-status-control').hidden=screen!=='history';$('history-status').value=historyStatus;$('queue-group-control').hidden=screen!=='processing';$('queue-group').value=queueGrouping;renderWaitingControls();$('queue-status-control').hidden=true;$('queue-status').value=queueStatus;$('run').hidden=screen!=='processing';$('run').disabled=(!lib&&!Array.isArray(state.global_queue))||(!state.tasks.some(t=>t.status==='queued'&&(Array.isArray(state.global_queue)||t.library===libraryId))&&!(state.file_jobs||[]).some(j=>j.phase==='waiting'))||(!featureAvailable('task_queues')&&Boolean(state.queue_running));$('run').textContent=Array.isArray(state.global_queue)?'Run all libraries':featureAvailable('task_queues')?'Run all task queues':state.queue_running?'Queue running…':'Run queue';$('scan').hidden=screen!=='library';$('library-settings').hidden=screen!=='library';$('scan').disabled=!lib;$('library-settings').disabled=!lib;
 $('library-tools').hidden=screen!=='library';renderSelection();
 const scan=state.scans?.[libraryId];$('scan-status').textContent=scan?.running?'Scanning · '+scan.count+' files'+(scan.skipped_reserved?' · '+scan.skipped_reserved+' reserved files skipped':''):scan?.error||'';
 const content=screen==='review'?renderReviewInbox():screen==='processing'?renderProcessing():screen==='history'?renderHistory():renderFileList(workspaceFiles());$('tasks').replaceChildren(...content);$('collapse-folders').hidden=screen!=='library'||!['folder','task'].includes(activeGrouping);$('collapse-folders').textContent=activeGrouping==='task'?'Collapse all task groups':'Collapse all folders';$('collapse-folders').title=$('collapse-folders').textContent;$('collapse-folders').disabled=!content.some(group=>group.matches('details.file-group'));$('empty').hidden=screen==='review'?reviewInboxRows().length>0:content.length>0;$('empty').querySelector('h2').textContent=screen==='review'?'No results awaiting review.':screen==='processing'?'No jobs in this view.':screen==='history'?'No history yet.':searchText?'No matching files.':libraryView==='attention'?'No files need attention.':libraryView==='completed'?'No completed files yet.':'No scanned files yet.';$('empty').querySelector('p').textContent=screen==='library'?'Choose another view, search your library, or scan for new files.':screen==='processing'?'Choose another status above, or queue work from a library.':'Browse your library to choose the next task.';
 const globalRunning=state.tasks.filter(t=>t.status==='running'),globalPublishing=state.tasks.filter(t=>t.status==='publishing'),globalWaiting=state.tasks.filter(t=>t.status==='queued'),globalReady=state.tasks.filter(t=>t.status==='awaiting_review'),target=globalPublishing[0]||globalRunning[0]||globalWaiting[0]||globalReady[0];const activeCleanups=(state.cleanup_jobs||[]).filter(j=>j.phase==='deleting');const strip=$('processing-strip');strip.hidden=screen==='processing';strip.replaceChildren();strip.append(node('span',globalRunning.length||globalPublishing.length||globalWaiting.length?'● '+globalRunning.length+' processing · '+globalPublishing.length+' publishing · '+globalWaiting.length+' waiting':'● No active processing'));if(globalPublishing[0]||globalRunning[0])strip.append(progressView(globalPublishing[0]||globalRunning[0]));if(activeCleanups.length){strip.append(node('span',activeCleanups.length+' cleanup running'));if(!target)strip.append(button('View queue',()=>{if(activeCleanups[0].library!==libraryId&&chooseLibrary(activeCleanups[0].library)===false)return;setScreen('processing');},'subtle'));}if(target)strip.append(button('View queue',()=>{if(target.library!==libraryId&&chooseLibrary(target.library)===false)return;setScreen('processing');},'subtle'));
 document.querySelectorAll('[data-progress-task]').forEach(box=>{const task=state.tasks.find(t=>t.id===box.dataset.progressTask);if(task)updateProgressView(box,task);});
 if(inspectorMode==='overview'&&selectedAssetId&&inspectorOpen()){const a=catalogIndex().byId.get(selectedAssetId),signature=a?JSON.stringify([a.item,a.blocked,fileTasks(a).map(t=>[t.id,t.status,t.version,t.error])]):'';if(signature!==overviewSignature&&a)renderAssetOverview(a,signature);}
 if(fileRowCache.size>10000)fileRowCache.clear();
}
async function openAssetOverview(id){if(!prepareInspector())return;const asset=catalogIndex().byId.get(id);if(!asset)return;selectedAssetId=id;inspectorMode='overview';openedTask='asset:'+id;renderAssetOverview(asset);showInspector();render();}
function renderAssetOverview(asset,signature=''){
 overviewSignature=signature||JSON.stringify([asset.item,asset.blocked,fileTasks(asset).map(t=>[t.id,t.status,t.version,t.error])]);
 const ready=fileTasks(asset).some(t=>t.status==='awaiting_review'&&['upscale','optimize','join'].includes(t.kind));
 $('task-kind').textContent=ready?'READY TO PUBLISH':'REVIEW SUGGESTIONS';$('task-title').textContent=fileName(asset);$('task-reason').hidden=true;$('task-feedback').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();if(asset.item?.thumb)detail.append(thumbnail(asset,true));detail.append(node('p',metaLine(asset),'muted'));
 const links=node('div',undefined,'inspector-links');links.append(button('Metadata Manager',async()=>{const t=await api('metadata/task',{asset:asset.id});await refresh();await openTask(t.id);},'text-button'));
 links.append(button('Artwork Manager',async()=>{const t=await api('metadata/task',{asset:asset.id});await refresh();await openTask(t.id,'artwork');},'text-button'));
 const tools=node('details',undefined,'file-menu');tools.append(node('summary','File tools'));for(const [label,kind] of [['Rename file','rename'],['Join parts','join'],['Collection & playlist','group']])tools.append(button(label,()=>openFileOperation(catalogIndex().byId.get(asset.id),kind),'subtle'));tools.append(button('Manage tasks',()=>openTaskManager(asset.id),'subtle'));links.append(tools);detail.append(links);
 if(asset.availability_error||asset.blocked)detail.append(node('p',asset.availability_error||asset.blocked,'task-error'));
 const tasks=fileTasks(asset).filter(t=>!HISTORY_TASK_STATES.has(t.status));
 if(!ready&&!tasks.some(t=>selected.has(t.id))){const first=tasks.find(canQueue);if(first)selected.add(first.id);}
 if(!tasks.length)detail.append(node('p','No pending work for this file.','muted'));
 for(const task of tasks){const row=node('div',undefined,'suggestion-row'),check=node('input');check.type='checkbox';check.disabled=!canQueue(task);check.checked=selected.has(task.id);check.setAttribute('aria-label','Select '+(TASK_LABELS[task.kind]||task.kind));check.onchange=()=>{check.checked?selected.add(task.id):selected.delete(task.id);updateQueueButton();};const text=node('div'),publishable=task.status==='awaiting_review'&&['upscale','optimize','join'].includes(task.kind);text.append(node('strong',TASK_LABELS[task.kind]||task.kind),node('p',publishable?'Ready to publish':task.error||task.reason,'muted'));row.append(check,text,button(publishable?'Review & Publish':'Review',()=>openTask(task.id),'subtle'));detail.append(row);}
 const history=fileTasks(asset).filter(t=>HISTORY_TASK_STATES.has(t.status));if(history.length){const box=node('details',undefined,'inspector-history');box.append(node('summary','Task history ('+history.length+')'));for(const task of history)box.append(button((TASK_LABELS[task.kind]||task.kind)+' · '+task.status,()=>openTask(task.id),'text-button'));detail.append(box);}
 const queue=button('Queue selected tasks',async()=>{const currentTasks=fileTasks(catalogIndex().byId.get(asset.id)),chosen=currentTasks.filter(t=>selected.has(t.id)&&canQueue(t));if(!chosen.length){const next=currentTasks.find(t=>['recommendation','blocked','failed','awaiting_review'].includes(t.status));if(next)return openTask(next.id);const active=currentTasks.find(t=>['queued','running','publishing'].includes(t.status));if(active){setScreen('processing');return openTask(active.id);}return;}let count=0;const errors=[];for(const task of chosen){try{await api('task/action',{id:task.id,version:task.version,action:'queue'});selected.delete(task.id);count++;}catch(error){errors.push(error.message);}}await refresh();toast(count+' queued'+(errors.length?' · '+errors.join('; '):''),Boolean(errors.length));},'primary');
 function updateQueueButton(){const count=fileTasks(asset).filter(t=>selected.has(t.id)&&canQueue(t)).length;queue.textContent=count?'Queue '+count+' selected '+(count===1?'task':'tasks'):tasks.some(t=>['recommendation','blocked','failed','awaiting_review'].includes(t.status))?'Review next suggestion':'View in Processing';queue.disabled=!tasks.length;queue.hidden=!tasks.length;}
 actions.append(queue);updateQueueButton();
}

function editorTabs(container,groups){
 const nav=node('nav',undefined,'editor-tabs');nav.setAttribute('aria-label','Metadata sections');nav.setAttribute('role','tablist');
 const buttons=[];groups.forEach(([label,sections],index)=>{const b=button(label,()=>select(index),'subtle');b.setAttribute('role','tab');buttons.push(b);nav.append(b);});
 function select(index){groups.forEach(([,sections],i)=>sections.forEach(section=>section.hidden=i!==index));buttons.forEach((b,i)=>{b.classList.toggle('active',i===index);b.setAttribute('aria-selected',String(i===index));});}
 container.prepend(nav);select(0);
}
function openTaskManager(id){
 if(!prepareInspector())return;const asset=catalogIndex().byId.get(id);if(!asset)return;inspectorMode='tasks';openedTask='tasks:'+id;
 $('task-kind').textContent='TASKS';$('task-title').textContent=fileName(asset);$('task-reason').hidden=true;$('task-feedback').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();
 for(const task of fileTasks(asset)){const row=node('section',undefined,'managed-task');row.append(node('strong',TASK_LABELS[task.kind]||task.kind),node('p',taskStatusLabel(task.status),'muted'),button('Review',()=>openTask(task.id),'subtle'),taskControls(task,true));detail.append(row);}
 showInspector();
}

function renderArtworkDrafts(container,library,kind,asset,tasks){
 container.replaceChildren();
 const drafts=tasks.filter(t=>t.library===library&&t.kind==='artwork'&&t.plan?.kind===kind&&t.plan.candidate&&(t.asset===asset||t.plan.assets?.includes(asset))&&['awaiting_review','blocked','failed','publishing'].includes(t.status));
 if(!drafts.length)return;
 container.append(node('p','Saved locally for review; current Plex artwork changes only after publishing.','muted'));
 for(const draft of [...drafts].reverse()){
  const card=node('section'),image=node('img');image.className='editor-image';image.alt='Saved '+ARTWORK_LABELS[kind].toLowerCase()+' draft';image.src='/api/folders/image?'+new URLSearchParams({photo:draft.plan.candidate});
  card.append(image,node('p',draft.status.replaceAll('_',' ')),button('Review & publish '+ARTWORK_LABELS[kind].toLowerCase(),()=>openTask(draft.id),'subtle'));container.append(card);
 }
}

const groupSelectionVersions=new Map();let currentReviewBatch=null,batchPage=0,batchPoll=null,batchSignature='',groupQueueProgress=null,bulkDecisionBusy=false;
function pruneGroupSelection(){
 const tasks=new Map(state.tasks.map(t=>[t.id,t]));
 for(const [id,version] of groupSelectionVersions){const task=tasks.get(id);if(!task||task.deleted||task.version!==version||!['recommendation','blocked','failed','awaiting_review'].includes(task.status)){selected.delete(id);groupSelectionVersions.delete(id);}}
}
function selectTaskRows(rows,enabled){for(const task of rows){if(enabled){selected.add(task.id);groupSelectionVersions.set(task.id,task.version);}else{selected.delete(task.id);groupSelectionVersions.delete(task.id);}}}
function groupTaskRows(group){const rows=group.files.flatMap(attentionTasks).filter(t=>t.kind===group.id&&!t.deleted&&taskAvailable(t));return [...new Map(rows.map(t=>[t.id,t])).values()];}
function reviewableRows(rows){return rows.filter(t=>selected.has(t.id)&&t.status==='awaiting_review'&&['upscale','optimize'].includes(t.kind));}
function bulkTaskControls(rows){
 const controls=node('div',undefined,'bulk-group-actions'),count=rows.filter(t=>selected.has(t.id)).length;if(!rows.length){controls.hidden=true;return controls;}
 const select=button(count===rows.length?'Clear selection ('+count+')':'Select all '+rows.length,()=>{selectTaskRows(rows,count!==rows.length);render();},'subtle');select.disabled=Boolean(groupQueueProgress);controls.append(select);
 const chosen=rows.filter(t=>selected.has(t.id)),needsPreset=chosen.filter(t=>t.kind==='optimize'&&canQueueWithSettings(t,{handbrake_preset:'pending-choice'}));
 const queueable=chosen.filter(canQueue);
 if(chosen.some(t=>t.status!=='awaiting_review')){const candidates=needsPreset.length?needsPreset:queueable,action=button('Queue selected ('+candidates.length+')'+(needsPreset.length?'…':''),()=>run(()=>needsPreset.length?chooseBulkEncodingPreset(needsPreset):queueTaskRows(queueable)),'primary');action.disabled=Boolean(groupQueueProgress)||!candidates.length;controls.append(action);}
 const emptyMetadata=chosen.filter(t=>t.kind==='metadata'&&!Object.keys(t.plan?.changes||{}).length);if(emptyMetadata.length)controls.append(node('span',emptyMetadata.length+' need metadata edits before they can be queued. Open a file to edit, or use Edit folder to apply shared changes.','muted'));
 if(groupQueueProgress?.library===libraryId){const progress=node('span',queueProgressText(),'muted');progress.setAttribute('data-group-queue-status','');progress.setAttribute('role','status');controls.append(progress);}
 const review=reviewableRows(rows);if(review.length){const action=button('Review selected ('+review.length+')'+(featureAvailable('bulk_review')?'':' · Update pending'),()=>beginBulkReview(review),'primary');action.disabled=!featureAvailable('bulk_review');controls.append(action);}
 if(review.length&&featureAvailable('bulk_decisions'))for(const [action,label] of [['accept','Accept & Publish Selected'],['reject','Reject Selected']]){const control=button(label+' ('+review.length+')',()=>decideSelectedResults(review,action),action==='accept'?'primary':'subtle');control.disabled=bulkDecisionBusy;controls.append(control);}
 controls.append(node('span',count+' selected · all matching tasks in this group','muted'));
 for(const control of controls.querySelectorAll('button'))control.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();});
 return controls;
}
function canQueueWithSettings(task,settings={}){return canQueue(task.kind==='optimize'&&settings.handbrake_preset?{...task,plan:{...task.plan,handbrake_preset:settings.handbrake_preset}}:task);}
async function chooseBulkEncodingPreset(rows){
 if(!prepareInspector())return;
 const snapshot=rows.map(t=>({...t}));inspectorMode='bulk-encoding';openedTask=null;
 $('task-kind').textContent='OPTIMIZE ENCODING';$('task-title').textContent='Queue '+snapshot.length+' selected encodes';$('task-reason').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();
 detail.append(node('p','Choose one installed HandBrake preset for these selected tasks. They will wait in Queue; this does not start processing.','muted'));
 const label=node('label','Encoding preset'),select=node('select'),note=node('p','Loading installed presets…','muted');label.append(select);detail.append(label,note);
 const remember=node('input');remember.type='checkbox';remember.checked=featureAvailable('unattended_runs');if(featureAvailable('unattended_runs')){const saved=node('label',undefined,'checkbox-label');saved.append(remember,document.createTextNode(' Remember preset for these libraries'));detail.append(saved);}
 const queue=button('Queue '+snapshot.length+' selected encodes',()=>run(async()=>{if(!select.value)return;queue.disabled=true;await queueTaskRows(snapshot,{handbrake_preset:select.value,remember_preset:remember.checked});closeInspector(true);}),'primary');queue.disabled=true;actions.append(queue);showInspector();
 try{const result=await api('handbrake/presets');if(!result.available)throw Error(result.error||'HandBrakeCLI is unavailable');
  const empty=node('option','Choose an installed preset');empty.value='';select.append(empty);
  for(const preset of result.presets){const option=node('option',(preset.group?preset.group+' / ':'')+preset.name);option.value=preset.path;select.append(option);}
  const saved=[...new Set(snapshot.map(t=>state.processing_defaults?.[t.library]?.optimize?.handbrake_preset).filter(Boolean))],preferred=saved.length===1?saved[0]:state.config?.handbrake_preset;
  const match=result.presets.find(p=>p.path===preferred)||(result.presets.filter(p=>p.name===preferred).length===1?result.presets.find(p=>p.name===preferred):null);if(match)select.value=match.path;
  select.onchange=()=>{queue.disabled=!select.value;const preset=result.presets.find(p=>p.path===select.value);note.textContent=preset?.description||'Select a preset to queue the selected encodes.';};select.onchange();
 }catch(error){note.textContent=error.message;}
}
async function queueTaskRows(rows,settings={}){
 if(groupQueueProgress)return;
 const snapshot=rows.map(t=>({id:t.id,version:t.version})),targetLibrary=libraryId;let queued=0;const failures=[],queuedLibraries=new Set();
 groupQueueProgress={library:targetLibrary,completed:0,total:snapshot.length};render();
 try{for(const ref of snapshot){
  const task=state.tasks.find(t=>t.id===ref.id);
  if(!task||task.version!==ref.version||!canQueueWithSettings(task,settings))failures.push(ref.id+': task changed or is unavailable');
  else try{await api('task/action',{...ref,action:'queue',...(task.kind==='optimize'&&settings.handbrake_preset?{handbrake_preset:settings.handbrake_preset}:{})});selected.delete(ref.id);groupSelectionVersions.delete(ref.id);queued++;queuedLibraries.add(task.library);}catch(error){failures.push((task.title||ref.id)+': '+error.message);}
  groupQueueProgress.completed++;document.querySelectorAll('[data-group-queue-status]').forEach(el=>{el.textContent=queueProgressText();});
 }if(settings.remember_preset&&settings.handbrake_preset)for(const library of queuedLibraries){try{await api('processing-defaults',{library,kind:'optimize',values:{handbrake_preset:settings.handbrake_preset}});}catch(error){failures.push('Queued, but a library preset could not be remembered');}}
 }finally{groupQueueProgress=null;await refresh();}
 toast(queued+' queued'+(failures.length?' · '+failures.length+' failed: '+failures.slice(0,3).join('; '):' · Open Queue to start them.'),Boolean(failures.length));
 if(queued)document.getElementById('toast').append(button('View queue',()=>{if(targetLibrary!==libraryId&&chooseLibrary(targetLibrary)===false)return;setScreen('processing');},'subtle'));
}
function queueProgressText(){return 'Queueing '+groupQueueProgress.completed+' of '+groupQueueProgress.total+'…';}
function selectableTaskFile(asset,group){
 const rows=attentionTasks(asset).filter(t=>t.kind===group.id&&!t.deleted),wrapper=node('div',undefined,'bulk-file-row');
 if(!rows.length)return fileRow(asset,group.id);
 const check=node('input');check.type='checkbox';check.checked=rows.every(t=>selected.has(t.id));check.indeterminate=!check.checked&&rows.some(t=>selected.has(t.id));check.setAttribute('aria-label','Select '+fileName(asset)+' for '+group.title);
 check.onchange=()=>{selectTaskRows(rows,check.checked);render();};wrapper.append(check,fileRow(asset,group.id));return wrapper;
}
async function beginBulkReview(rows){
 if(!prepareInspector())return;
 const batch=await api('review-batch/prepare',{...reviewRowsScope(rows),tasks:rows.map(t=>({id:t.id,version:t.version}))});
 batchPage=0;openBulkReview(batch);
}
function reviewRowsScope(rows){const libraries=new Set(rows.map(t=>t.library));return libraries.size===1?{library:rows[0].library}:{scope:'all'};}
async function decideSelectedResults(rows,action){
 if(bulkDecisionBusy||!rows.length||!prepareInspector())return;
 const tasks=rows.map(t=>({id:t.id,version:t.version})),count=tasks.length;
 const libraries=[...new Set(rows.map(t=>t.library))].map(id=>state.libraries.find(lib=>lib.id===id)?.title||id).join(', ');
 if(action==='accept'&&!confirm('Accept & publish all '+count+' selected results from '+libraries+'? You may publish outputs you have not individually inspected and replace the library videos with unwanted results. Originals will be retained. Changed or failed tasks will be skipped.'))return;
 bulkDecisionBusy=true;render();
 try{
  const batch=await api('review-batch/'+(action==='accept'?'accept-selected':'reject-selected'),{...reviewRowsScope(rows),tasks,count,...(action==='accept'?{confirmation:'PUBLISH SELECTED WITHOUT INDIVIDUAL REVIEW'}:{})});
  for(const ref of tasks){selected.delete(ref.id);groupSelectionVersions.delete(ref.id);}await refresh();batchPage=0;openBulkReview(batch);
 }finally{bulkDecisionBusy=false;render();}
}
async function showReviewBatches(){
 if(!libraryId||!prepareInspector())return;
 const result=await api('review-batches?'+new URLSearchParams(screen==='processing'&&Array.isArray(state.global_queue)?{scope:'all'}:{library:libraryId}));
 inspectorMode='batch-list';openedTask=null;$('task-kind').textContent='BATCH REVIEWS';$('task-title').textContent='Saved review batches';$('task-reason').hidden=true;
 const detail=$('task-detail');detail.replaceChildren();$('task-buttons').replaceChildren();
 for(const batch of result.batches)detail.append(button(batch.count+' results · '+batch.phase+' · '+new Date(batch.created).toLocaleString(),async()=>{batchPage=0;openBulkReview(await api('review-batch?'+new URLSearchParams({id:batch.id})));},'subtle'));
 if(!result.batches.length)detail.append(node('p','Select results in a task group to prepare a batch.'));
 showInspector();
}
function batchSummary(batch){const counts={};for(const item of batch.items)counts[item.status]=(counts[item.status]||0)+1;return batch.phase+' · '+Object.entries(counts).map(([key,value])=>value+' '+key).join(' · ');}
function openBulkReview(batch){
 clearTimeout(batchPoll);currentReviewBatch=batch;inspectorMode='batch-review';openedTask=null;batchSignature='';renderBulkReview(batch);showInspector();pollBulkReview();
}
function renderBulkReview(batch){
 const start=batchPage*20,items=batch.items.slice(start,start+20),signature=JSON.stringify([batch.id,batch.phase,batchPage,items]);
 const summary=$('bulk-review-summary');if(summary)summary.textContent=batchSummary(batch);
 if(signature===batchSignature)return;batchSignature=signature;
 $('task-kind').textContent='BATCH VIDEO REVIEW';$('task-title').textContent=batch.items.length+' selected results';$('task-reason').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();
 const status=node('p',batchSummary(batch),'muted');status.id='bulk-review-summary';detail.append(status);
 detail.append(node('p',batch.automatic_publish?'Bulk acceptance confirmed. Comparisons and publication checks run before each installation; changed or failed tasks are skipped. Originals are retained.':batch.phase==='rejecting'?'Rejected results return to suggestions; their media and generated files are retained.':'Preparing comparisons does not publish. Review the selected results before confirming publication. Originals are retained beside published videos.','muted'));
 for(const item of items){
  const task=state.tasks.find(t=>t.id===item.id),card=node('section',undefined,'bulk-review-card');card.append(node('h3',task?.title||item.id),node('p',item.error||item.status,'muted'));
  if(item.status==='prepared'){
   const images=node('div',undefined,'comparison');for(const side of ['source','output']){const column=node('div');column.append(node('strong',side==='source'?'Original':'Processed'));for(let n=0;n<4;n++){const image=node('img');image.loading='lazy';image.src='/api/comparison/'+encodeURIComponent(item.id)+'/'+side+'/'+n+'.jpg';image.alt=side+' sample '+(n+1);column.append(image);}images.append(column);}card.append(images);
  }
  card.append(button('Open task',()=>openTask(item.id),'subtle'));detail.append(card);
 }
 const pages=Math.ceil(batch.items.length/20),pager=node('div',undefined,'bulk-group-actions');
 const previous=button('Previous',()=>{batchPage--;batchSignature='';renderBulkReview(currentReviewBatch);},'subtle');previous.disabled=!batchPage;
 const next=button('Next',()=>{batchPage++;batchSignature='';renderBulkReview(currentReviewBatch);},'subtle');next.disabled=batchPage+1>=pages;
 pager.append(previous,node('span','Page '+(batchPage+1)+' of '+pages),next);detail.append(pager);
 if(['preparing','publishing','rejecting'].includes(batch.phase))actions.append(button('Stop after current file',async()=>{await api('review-batch/stop',{id:batch.id});toast('Stopping after the current file finishes.');},'subtle'));
 if(batch.phase==='ready'&&!batch.automatic_publish){
  const count=batch.items.filter(item=>item.status==='prepared').length;
  if(count)actions.append(button('Accept & publish '+count+' results',async()=>{
   if(!confirm('I reviewed these '+count+' prepared comparisons and approve publishing them, retaining every original as filename-old.ext. Changed or failed tasks will be skipped.'))return;
   const result=await api('review-batch/publish',{id:batch.id,count});openBulkReview(result);
  },'primary'));
 }
 if(['interrupted','stopped'].includes(batch.phase))detail.append(node('p','Unfinished results remain available. Reselect them to create a new batch; no work is replayed automatically.','muted'));
}
async function pollBulkReview(){
 if(inspectorMode!=='batch-review'||!inspectorOpen()||!currentReviewBatch)return;
 try{const id=currentReviewBatch.id,batch=await api('review-batch?'+new URLSearchParams({id}));if(inspectorMode!=='batch-review'||currentReviewBatch.id!==id)return;currentReviewBatch=batch;renderBulkReview(batch);}catch(error){toast(error.message,true);return;}
 if(['preparing','publishing'].includes(currentReviewBatch.phase))batchPoll=setTimeout(pollBulkReview,2000);
}

function featureAvailable(name){return Boolean(serviceStatus?.capabilities?.includes(name));}

let currentCleanup=null,cleanupPoll=null;const cleanupSelected=new Set();
async function showBackupCleanup(){
 if(!libraryId||!prepareInspector())return;
 const receipt=await api('cleanup/preview',{library:libraryId});cleanupSelected.clear();openBackupCleanup(receipt);
}
function openBackupCleanup(receipt){
 clearTimeout(cleanupPoll);currentCleanup=receipt;inspectorMode='backup-cleanup';openedTask=null;
 $('task-kind').textContent='RETAINED ORIGINALS';$('task-title').textContent='Clean up original backups';$('task-reason').hidden=true;
 renderBackupCleanup();showInspector();pollBackupCleanup();
}
function renderBackupCleanup(){
 const receipt=currentCleanup,detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();
 const selectedRows=receipt.items.filter(row=>cleanupSelected.has(row.id)),bytes=selectedRows.reduce((sum,row)=>sum+row.bytes,0);
 detail.append(node('p','Only originals recorded by completed, verified publications are offered. Files are reverified before deletion. This permanently removes selected backups; the published videos stay in place.','muted'));
 const failed=receipt.items.filter(row=>row.status==='failed').length;
 detail.append(node('p',(receipt.phase==='complete'&&failed?'Finished with failures':receipt.phase)+' · '+receipt.items.filter(row=>row.status==='deleted').length+' deleted · '+failed+' failed','muted'));
 if(receipt.phase==='deleting'&&receipt.current)detail.append(node('p',receipt.current.phase+' · '+receipt.current.title,'muted'));
 if(receipt.phase==='preview'){
  detail.append(button(cleanupSelected.size===receipt.items.length?'Clear selection':'Select all '+receipt.items.length,()=>{const clear=cleanupSelected.size===receipt.items.length;cleanupSelected.clear();if(!clear)for(const row of receipt.items)cleanupSelected.add(row.id);renderBackupCleanup();},'subtle'));
 }
 for(const row of receipt.items){
  const card=node('section',undefined,'bulk-review-card');card.append(node('strong',row.title),node('p',row.backup+' · '+formatBytes(row.bytes),'muted'));
  if(receipt.phase==='preview'){
   const check=node('input');check.type='checkbox';check.checked=cleanupSelected.has(row.id);check.onchange=()=>{check.checked?cleanupSelected.add(row.id):cleanupSelected.delete(row.id);renderBackupCleanup();};
   const label=node('label',' Delete this retained original');label.prepend(check);card.append(label);
  }else card.append(node('p',row.error||row.status,'muted'));
  detail.append(card);
 }
 if(!receipt.items.length)detail.append(node('p','No eligible retained originals found.'));
 for(const blocked of receipt.blocked||[]){const card=node('section',undefined,'bulk-review-card');card.append(node('p',blocked.reason,'muted'));if(blocked.recoverable)card.append(button('Restore retained original',async()=>{await api('cleanup/restore',{id:blocked.id});await showBackupCleanup();},'subtle'));detail.append(card);}
 if(receipt.phase==='preview'&&selectedRows.length){
  const remove=button('Permanently delete '+selectedRows.length+' backups · '+formatBytes(bytes),async()=>{
   if(!confirm('Permanently delete these '+selectedRows.length+' retained originals ('+formatBytes(bytes)+')? This cannot be undone. Published videos will remain.'))return;
   remove.disabled=true;
   try{openBackupCleanup(await api('cleanup/delete',{id:receipt.id,tasks:selectedRows.map(row=>row.id),count:selectedRows.length,confirmation:'DELETE RETAINED ORIGINALS'}));}
   catch(error){const observed=await api('cleanup?'+new URLSearchParams({id:receipt.id}));if(observed.phase!=='preview')openBackupCleanup(observed);else{remove.disabled=false;throw error;}}
  },'primary');actions.append(remove);
 }
 for(const previous of receipt.history||[])detail.append(button('Cleanup receipt · '+previous.phase+' · '+new Date(previous.created).toLocaleString(),async()=>openBackupCleanup(await api('cleanup?'+new URLSearchParams({id:previous.id}))),'subtle'));
}
async function pollBackupCleanup(){
 if(inspectorMode!=='backup-cleanup'||!inspectorOpen()||currentCleanup?.phase!=='deleting')return;
 try{const id=currentCleanup.id,receipt=await api('cleanup?'+new URLSearchParams({id}));if(inspectorMode!=='backup-cleanup'||currentCleanup.id!==id)return;currentCleanup=receipt;renderBackupCleanup();}catch(error){toast(error.message,true);return;}
 if(currentCleanup.phase==='deleting')cleanupPoll=setTimeout(pollBackupCleanup,2000);
}

function updateFeatureControls(){for(const [id,capability] of [['review-batches','bulk_review'],['cleanup-backups','backup_cleanup']]){const control=$(id);if(control)control.disabled=!featureAvailable(capability);}}
