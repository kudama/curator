'use strict';
// Navigation and presentation only. Editors continue to use the existing approved workflows.
const collapsedGroups=new Set(),fileRowCache=new Map();let overviewSignature='';
function inspectorOpen(){return !$('task-dialog').hidden;}
function prepareInspector(){
 const close=$('task-dialog').querySelector('[data-close]');
 if(close.disabled){toast('Wait for the current save to finish.',true);return false;}
 if(inspectorDirty&&!confirm('Discard unsaved changes in the review panel?'))return false;
 inspectorDirty=false;overviewSignature='';return true;
}
function showInspector(){$('task-dialog').hidden=false;$('inspector-empty').hidden=true;$('task-title').tabIndex=-1;$('task-title').focus({preventScroll:true});}
function closeInspector(force=false){if(!force&&!prepareInspector())return;inspectorDirty=false;openedTask=null;inspectorMode=null;$('task-dialog').hidden=true;$('inspector-empty').hidden=false;document.querySelector('.workbench').classList.remove('review-wide');$('inspector-expand').setAttribute('aria-label','Expand review panel');$('inspector-expand').title='Expand review panel';document.querySelector('.file-entry[aria-pressed="true"]')?.focus({preventScroll:true});}
function fileName(asset){return (asset.plex_path||asset.local_path||'').split('/').pop()||asset.title;}
function matchesSearch(asset){return !searchText||[fileName(asset),asset.title,asset.plex_path].join(' ').toLocaleLowerCase().includes(searchText);}
function fileTasks(asset){if(!asset)return [];return (catalogIndex().byAsset.get(asset.id)||[]).filter(t=>t.library===libraryId);}
function attentionTasks(asset){return fileTasks(asset).filter(t=>['recommendation','blocked','failed','awaiting_review'].includes(t.status));}
function libraryFiles(){return state.assets.filter(a=>a.library===libraryId&&a.present!==false);}
function workspaceFiles(){return libraryFiles().filter(matchesSearch).filter(a=>screen!=='library'||libraryView==='files'||(libraryView==='completed'?movieCompleted(a):attentionTasks(a).length>0));}
function fileBadge(asset){
 const tasks=fileTasks(asset);
 if(tasks.some(t=>t.status==='publishing'))return {text:'Publishing',kind:'running'};
 if(tasks.some(t=>t.status==='running'))return {text:'Processing',kind:'running'};
 if(tasks.some(t=>['blocked','failed'].includes(t.status)))return {text:'Needs attention',kind:'issue'};
 if(tasks.some(t=>t.status==='awaiting_review'))return {text:tasks.some(t=>['upscale','optimize','join'].includes(t.kind)&&t.status==='awaiting_review')?'Ready to publish':'Review suggestions',kind:'ready'};
 if(tasks.some(t=>t.status==='queued'))return {text:'In queue',kind:'waiting'};
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
function initWorkbench(){
 document.querySelectorAll('[data-screen]').forEach(b=>b.onclick=()=>setScreen(b.dataset.screen));
 $('inspector-expand').onclick=()=>{const wide=document.querySelector('.workbench').classList.toggle('review-wide');$('inspector-expand').setAttribute('aria-label',wide?'Restore review panel':'Expand review panel');$('inspector-expand').title=wide?'Restore review panel':'Expand review panel';};
 $('file-search').oninput=e=>{searchText=e.target.value.trim().toLocaleLowerCase();render();};
 $('folder-choice').onchange=e=>{const id=e.target.value;e.target.value='';if(id)run(()=>openFolder(id));};
 window.addEventListener('beforeunload',e=>{if(inspectorDirty){e.preventDefault();e.returnValue='';}});
 $('task-detail').addEventListener('input',()=>{if(inspectorMode==='file-tools')inspectorDirty=true;});
 $('task-dialog').addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();closeInspector();}});
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
function renderFileList(files){
 if(activeGrouping==='movie')return files.map(a=>fileRow(a));
 const groups=new Map();
 if(activeGrouping==='folder'&&libraryView==='files'&&!searchText)for(const folder of (state.folders||[]).filter(f=>f.library===libraryId&&!f.parent))groups.set(folder.id,{id:folder.id,title:folderLabel(folder),folder,files:[]});
 for(const asset of files){const folder=folderFor(asset),kinds=activeGrouping==='task'?[...new Set(attentionTasks(asset).map(t=>t.kind))]:[];
  const keys=activeGrouping==='folder'?[{id:folder?.id||asset.plex_path.split('/').slice(0,-1).join('/'),title:folder?folderLabel(folder):'Other files',folder}]:kinds.length?kinds.map(kind=>({id:kind,title:TASK_LABELS[kind]||kind})):[{id:'other',title:'Other files'}];
  for(const key of keys){if(!groups.has(key.id))groups.set(key.id,{...key,files:[]});groups.get(key.id).files.push(asset);}
 }
 return [...groups.values()].map(group=>{const section=rememberGroup(node('details',undefined,'file-group collapsible-group'),libraryId+':'+activeGrouping+':'+group.id),head=node('summary',undefined,'file-group-heading');head.append(node('h3',(activeGrouping==='folder'?'▱  ':'')+group.title),node('span',String(group.files.length),'muted'));
  if(group.folder){const edit=button(group.folder.mapped===false?'Set Mac path':'Edit folder',()=>group.folder.mapped===false?openLibrarySettings():openFolder(group.folder.id),'subtle');edit.addEventListener('click',e=>{e.stopPropagation();e.preventDefault();});head.append(edit);}section.append(head,...group.files.map(a=>fileRow(a,group.id)));if(!group.files.length)section.append(node('p',group.folder?.mapped===false?'Set the Mac path to scan files in this location.':'No scanned files directly in this folder.','empty-folder-note'));return section;});
}
function processingTaskCard(task){
 const asset=catalogIndex().byId.get(task.asset),card=node('article',undefined,'processing-card'),main=node('div',undefined,'processing-card-main');
 main.append(thumbnail(asset||{}));const text=node('div',undefined,'processing-card-text');text.append(node('strong',asset?fileName(asset):task.title),node('p',(TASK_LABELS[task.kind]||task.kind)+' · '+(task.cancel_requested?'Cancelling…':task.status.replaceAll('_',' ')),'muted'));
 if(task.error)text.append(node('p',task.error,'task-error'));if(['running','publishing'].includes(task.status))text.append(progressView(task));
 if(task.status==='awaiting_review'&&task.result?.size_bytes)text.append(node('p',formatBytes(task.source?.size??asset?.fingerprint?.size)+' → '+formatBytes(task.result.size_bytes),'muted'));
 main.append(text);const actions=node('div',undefined,'processing-card-actions');actions.append(button(task.status==='awaiting_review'?(['upscale','optimize','join'].includes(task.kind)?'Compare & publish':'Review suggestions'):['blocked','failed'].includes(task.status)?'Inspect':'Details',()=>openTask(task.id),task.status==='awaiting_review'?'primary':'subtle'),taskControls(task));main.append(actions);card.append(main);return card;
}
function renderProcessing(){
 const tasks=state.tasks.filter(t=>t.library===libraryId&&['queued','running','publishing','awaiting_review','failed','blocked'].includes(t.status)&&(queueStatus==='all'||t.status===queueStatus)&&(!searchText||[t.title,catalogIndex().byId.get(t.asset)?.plex_path,TASK_LABELS[t.kind]].join(' ').toLowerCase().includes(searchText)));
 const groups=[['Publishing',['publishing']],['Processing',['running']],['Waiting',['queued']],['Ready to publish / review',['awaiting_review']],['Needs attention',['failed','blocked']]];
 return groups.flatMap(([title,statuses])=>{const rows=tasks.filter(t=>statuses.includes(t.status));if(!rows.length)return [];const section=rememberGroup(node('details',undefined,'processing-group collapsible-group'),libraryId+':processing:'+title),heading=node('summary',undefined,'processing-group-heading');heading.append(node('h2',title+' ('+rows.length+')'));section.append(heading,...rows.map(processingTaskCard));return [section];});
}
function renderHistory(){
 return state.tasks.filter(t=>t.library===libraryId&&HISTORY_TASK_STATES.has(t.status)&&(!searchText||[t.title,catalogIndex().byId.get(t.asset)?.plex_path,TASK_LABELS[t.kind]].join(' ').toLowerCase().includes(searchText))).sort((a,b)=>(b.updated||'').localeCompare(a.updated||'')).map(task=>{const row=node('article',undefined,'history-row'),text=node('div');text.append(node('strong',catalogIndex().byId.get(task.asset)?fileName(catalogIndex().byId.get(task.asset)):task.title),node('p',(TASK_LABELS[task.kind]||task.kind)+' · '+task.status.replaceAll('_',' ')+' · '+new Date(task.updated||task.created).toLocaleString(),'muted'));row.append(text,button('View',()=>openTask(task.id),'subtle'),taskControls(task));return row;});
}
function renderWorkbench(){
 $('libraries').replaceChildren(...state.libraries.map(lib=>button(lib.title,()=>chooseLibrary(lib.id),lib.id===libraryId?'selected':'')));
 document.querySelectorAll('[data-screen]').forEach(b=>b.classList.toggle('active',b.dataset.screen===screen));
 const lib=current(),assets=libraryFiles(),tasks=state.tasks.filter(t=>t.library===libraryId),running=tasks.filter(t=>t.status==='running'),publishing=tasks.filter(t=>t.status==='publishing'),waiting=tasks.filter(t=>t.status==='queued'),ready=tasks.filter(t=>t.status==='awaiting_review');
 $('library-title').textContent=screen==='library'?(lib?.title||'Your library'):screen==='processing'?'Processing':'History';$('library-type').textContent=screen==='library'?(lib?.profile==='home'?'HOME MOVIES':'TV & MOVIES'):(lib?.title||'WORKSPACE');
 $('library-note').textContent=screen==='library'?'Review what needs attention, one file at a time.':screen==='processing'?running.length+' processing · '+publishing.length+' publishing · '+waiting.length+' waiting · '+ready.length+' ready to review':'Completed, cancelled and resolved work. Media files stay in your library.';
 $('asset-count').textContent=assets.length;$('attention-count').textContent=assets.filter(a=>attentionTasks(a).length).length;$('completed-count').textContent=assets.filter(movieCompleted).length;
 $('finding-count').textContent=tasks.filter(t=>t.status==='recommendation').length;$('queue-count').textContent=running.length+waiting.length;$('review-count').textContent=ready.length;$('nav-processing-count').textContent=running.length+publishing.length+waiting.length+ready.length||'';
 $('filters').hidden=screen!=='library';document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===libraryView));
 $('group-by-control').hidden=screen!=='library';$('group-by').value=activeGrouping;$('folder-choice-label').hidden=screen!=='library';$('queue-status-control').hidden=screen!=='processing';$('queue-status').value=queueStatus;$('run').hidden=screen!=='processing';$('run').disabled=!lib||!waiting.length||Boolean(state.queue_running);$('run').textContent=state.queue_running?'Queue running…':'Run queue';$('scan').hidden=screen!=='library';$('library-settings').hidden=screen!=='library';$('scan').disabled=!lib;$('library-settings').disabled=!lib;
 const folders=(state.folders||[]).filter(f=>f.library===libraryId),chooser=$('folder-choice'),folderSignature=JSON.stringify(folders.map(f=>[f.id,f.path,f.count,f.mapped]));if(chooser.dataset.signature!==folderSignature){chooser.dataset.signature=folderSignature;chooser.replaceChildren(node('option','Folder metadata…'));chooser.options[0].value='';for(const folder of folders){const option=node('option',folderLabel(folder)+' ('+folder.count+')'+(folder.mapped===false?' · Mac path needed':''));option.value=folder.id;chooser.append(option);}}chooser.disabled=!folders.length;
 $('library-tools').hidden=screen!=='library';renderSelection();
 const scan=state.scans?.[libraryId];$('scan-status').textContent=scan?.running?'Scanning · '+scan.count+' files'+(scan.skipped_reserved?' · '+scan.skipped_reserved+' reserved files skipped':''):scan?.error||'';
 const content=screen==='processing'?renderProcessing():screen==='history'?renderHistory():renderFileList(workspaceFiles());$('tasks').replaceChildren(...content);$('empty').hidden=content.length>0;$('empty').querySelector('h2').textContent=screen==='processing'?'Nothing in processing.':screen==='history'?'No history yet.':searchText?'No matching files.':libraryView==='attention'?'No files need attention.':libraryView==='completed'?'No completed files yet.':'No scanned files yet.';$('empty').querySelector('p').textContent=screen==='library'?'Choose another view, search your library, or scan for new files.':'Browse your library to choose the next task.';
 const globalRunning=state.tasks.filter(t=>t.status==='running'),globalPublishing=state.tasks.filter(t=>t.status==='publishing'),globalWaiting=state.tasks.filter(t=>t.status==='queued'),globalReady=state.tasks.filter(t=>t.status==='awaiting_review'),target=globalPublishing[0]||globalRunning[0]||globalWaiting[0]||globalReady[0];const strip=$('processing-strip');strip.hidden=screen==='processing';strip.replaceChildren();strip.append(node('span',globalRunning.length||globalPublishing.length||globalWaiting.length?'● '+globalRunning.length+' processing · '+globalPublishing.length+' publishing · '+globalWaiting.length+' waiting':'● No active processing'));if(globalPublishing[0]||globalRunning[0])strip.append(progressView(globalPublishing[0]||globalRunning[0]));if(target)strip.append(button('View processing',()=>{if(target.library!==libraryId&&chooseLibrary(target.library)===false)return;setScreen('processing');},'subtle'));
 document.querySelectorAll('[data-progress-task]').forEach(box=>{const task=state.tasks.find(t=>t.id===box.dataset.progressTask);if(task)updateProgressView(box,task);});
 if(inspectorMode==='overview'&&selectedAssetId&&inspectorOpen()){const a=catalogIndex().byId.get(selectedAssetId),signature=a?JSON.stringify([a.item,a.blocked,fileTasks(a).map(t=>[t.id,t.status,t.version,t.error])]):'';if(signature!==overviewSignature&&a)renderAssetOverview(a,signature);}
 if(fileRowCache.size>10000)fileRowCache.clear();
}
async function openAssetOverview(id){if(!prepareInspector())return;const asset=catalogIndex().byId.get(id);if(!asset)return;selectedAssetId=id;inspectorMode='overview';openedTask='asset:'+id;renderAssetOverview(asset);showInspector();render();}
function renderAssetOverview(asset,signature=''){
 overviewSignature=signature||JSON.stringify([asset.item,asset.blocked,fileTasks(asset).map(t=>[t.id,t.status,t.version,t.error])]);
 $('task-kind').textContent='REVIEW SUGGESTIONS';$('task-title').textContent=fileName(asset);$('task-reason').hidden=true;$('task-feedback').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();if(asset.item?.thumb)detail.append(thumbnail(asset,true));detail.append(node('p',metaLine(asset),'muted'));
 const links=node('div',undefined,'inspector-links');links.append(button('Edit metadata',async()=>{const t=await api('metadata/task',{asset:asset.id});await refresh();await openTask(t.id);},'text-button'));
 const tools=node('details',undefined,'file-menu');tools.append(node('summary','File tools'));for(const [label,kind] of [['Rename file','rename'],['Join parts','join'],['Collection & playlist','group']])tools.append(button(label,()=>openFileOperation(catalogIndex().byId.get(asset.id),kind),'subtle'));tools.append(button('Manage tasks',()=>openTaskManager(asset.id),'subtle'));links.append(tools);detail.append(links);
 if(asset.availability_error||asset.blocked)detail.append(node('p',asset.availability_error||asset.blocked,'task-error'));
 const tasks=fileTasks(asset).filter(t=>!HISTORY_TASK_STATES.has(t.status));
 if(!tasks.some(t=>selected.has(t.id))){const first=tasks.find(canQueue);if(first)selected.add(first.id);}
 if(!tasks.length)detail.append(node('p','No pending work for this file.','muted'));
 for(const task of tasks){const row=node('div',undefined,'suggestion-row'),check=node('input');check.type='checkbox';check.disabled=!canQueue(task);check.checked=selected.has(task.id);check.setAttribute('aria-label','Select '+(TASK_LABELS[task.kind]||task.kind));check.onchange=()=>{check.checked?selected.add(task.id):selected.delete(task.id);updateQueueButton();};const text=node('div');text.append(node('strong',TASK_LABELS[task.kind]||task.kind),node('p',task.error||task.reason,'muted'));row.append(check,text,button('Review',()=>openTask(task.id),'subtle'));detail.append(row);}
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
 for(const task of fileTasks(asset)){const row=node('section',undefined,'managed-task');row.append(node('strong',TASK_LABELS[task.kind]||task.kind),node('p',task.status.replaceAll('_',' '),'muted'),button('Review',()=>openTask(task.id),'subtle'),taskControls(task,true));detail.append(row);}
 showInspector();
}
