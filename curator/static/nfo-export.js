'use strict';
// The manifest belongs to the server. Checkboxes approve only its pinned revision.
function nfoPanel(title){
 if(!prepareInspector())return null;
 const token='nfo:'+clientId();openedTask=token;inspectorMode='nfo-export';inspectorDirty=false;
 $('task-kind').textContent='NFO EXPORT';$('task-title').textContent=title;$('task-reason').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();showInspector();return {token,detail,actions};
}
function nfoSelect(label,values,current){const wrap=node('label',label),select=node('select');select.setAttribute('aria-label',label);for(const [value,title] of values){const option=node('option',title);option.value=value;select.append(option);}select.value=current;wrap.append(select);return {wrap,select};}
async function openNfoExport(retry=null,targetLibrary=libraryId){
 const library=state.libraries.find(l=>l.id===targetLibrary);if(!library)return;
 const panel=nfoPanel('Generate NFO files');if(!panel)return;const {token,detail,actions}=panel;
 const selected=retry||selectedManagementFiles().map(a=>a.id),scope=nfoSelect('Scope',[['selected','Selected files ('+selected.length+')'],['folder','One folder'],['library','Entire library']],selected.length?'selected':'library');
 const folders=[...new Set(state.assets.filter(a=>a.library===library.id&&a.present!==false).map(a=>(a.plex_path||'').split('/').slice(0,-1).join('/')))].sort(),folder=nfoSelect('Folder',folders.map(f=>[f,f]),folders[0]||''),filter=nfoSelect('Include',[['all','All files'],['missing','Missing NFO'],['changed','New or changed metadata'],['failed','Previous partial / failed exports']],'all');
 detail.append(node('p',library.title,'muted'),node('p','Export current saved metadata and currently selected artwork beside your videos. Create missing files by default. Existing files are kept; Curator-written NFO updates require separate approval. No Plex refresh or settings change.'),scope.wrap,folder.wrap,filter.wrap);
 const note=node('p','','muted');detail.append(note);folder.wrap.hidden=scope.select.value!=='folder';
 const preview=button('Prepare preview',async()=>{if(preview.disabled)return;preview.disabled=true;note.textContent='Reading current metadata, selected artwork and destinations…';try{const record=await api('nfo/preview',{library:library.id,scope:scope.select.value,assets:selected,folder:folder.select.value,filter:filter.select.value});if(openedTask===token)await showNfoManifest(panel,record);}catch(error){note.textContent=error.message;preview.disabled=false;}},'primary');
 function validate(){folder.wrap.hidden=scope.select.value!=='folder';preview.disabled=scope.select.value==='selected'&&!selected.length||scope.select.value==='folder'&&!folders.length;}
 scope.select.onchange=validate;validate();
 actions.append(button('Recent exports',()=>openNfoExports(library.id),'text-button'),button('Cancel',()=>closeInspector(),'subtle'),preview);
}
async function openNfoExports(library){
 const panel=nfoPanel('Recent NFO exports');if(!panel)return;const {token,detail,actions}=panel;actions.append(button('Close',()=>closeInspector(),'subtle'));
 try{const result=await api('nfo/list',{library});if(openedTask!==token)return;for(const record of result.exports)detail.append(button(record.created+' · '+record.count+' items · '+record.phase,()=>openNfoManifest(record.id),'text-button'));if(!result.exports.length)detail.append(node('p','No NFO exports yet.'));}catch(error){detail.append(node('p',error.message,'error'));}
}
async function openNfoManifest(id){const panel=nfoPanel('NFO export');if(!panel)return;try{await showNfoManifest(panel,await api('nfo/status',{id}));}catch(error){panel.detail.append(node('p',error.message,'error'));panel.actions.append(button('Close',()=>closeInspector(),'subtle'));}}
async function showNfoManifest(panel,record){
 const {token,detail,actions}=panel;if(openedTask!==token)return;
 detail.replaceChildren();actions.replaceChildren();
 if(record.phase==='preparing'){
  detail.append(node('p','Preparing preview · '+record.items.length+' of '+record.assets.length+' items read','muted'),node('p','No destination files are written during preparation.'));
  actions.append(button('Cancel preparation',async()=>{try{await api('nfo/cancel',{id:record.id});if(openedTask===token)closeInspector(true);}catch(error){detail.append(node('p',error.message,'error'));}},'subtle'));
  setTimeout(async()=>{if(openedTask!==token)return;try{await showNfoManifest(panel,await api('nfo/status',{id:record.id}));}catch(error){if(openedTask===token){detail.append(node('p',error.message,'error'));actions.append(button('Retry status',()=>openNfoManifest(record.id),'text-button'));}}},700);return;
 }
 const reviewing=record.phase==='ready',selected=new Set(reviewing?record.items.filter(r=>r.phase==='ready').map(r=>r.asset):[]),updates=new Set();let page=0,busy=false;
 const counts={};for(const row of record.items)counts[row.phase]=(counts[row.phase]||0)+1;
 detail.append(node('p',(reviewing?'Review proposed export':record.phase.toUpperCase())+' · '+record.assets.length+(record.assets.length===1?' item · ':' items · ')+Object.entries(counts).map(([k,v])=>v+' '+k).join(' · '),'muted'));
 if(record.error)detail.append(node('p',record.error,'error'));
 detail.append(node('p','This is a portable export of supported fields and images, not a certified complete Plex backup. Missing artwork, cast portrait portability and unmapped fields are reported per item. Source media and existing Plex selections stay unchanged.','muted'));
 const list=node('div'),pages=node('div'),note=node('p','','muted');detail.append(list,pages,note);
 const approve=button('Approve & queue export',async()=>{if(busy||!selected.size)return;busy=true;approve.disabled=true;note.textContent='Checking reviewed source identities…';try{await api('nfo/queue',{id:record.id,revision:record.review_revision,assets:[...selected],updates:[...updates].filter(id=>selected.has(id))});if(openedTask===token){closeInspector(true);await refresh();toast('NFO package queued in File operations. Run that queue when ready.');}}catch(error){note.textContent=error.message;busy=false;approve.disabled=!selected.size;}},'primary');
 function render(){
  list.replaceChildren();for(const row of record.items.slice(page*25,(page+1)*25)){
   let updateControl=null;const box=node('details'),summary=node('summary'),check=node('input');check.type='checkbox';check.checked=selected.has(row.asset);check.disabled=!reviewing||row.phase!=='ready';check.setAttribute('aria-label','Export '+row.title);
   check.onclick=event=>event.stopPropagation();check.onchange=()=>{check.checked?selected.add(row.asset):selected.delete(row.asset);if(updateControl){updateControl.disabled=!check.checked;if(!check.checked){updates.delete(row.asset);updateControl.checked=false;}}approve.disabled=busy||!selected.size;};
   summary.append(check,node('span',row.title+' · '+row.phase));box.append(summary);if(row.reason||row.error)box.append(node('p',row.reason||row.error,'error'));
   for(const warning of row.warnings||[])box.append(node('p',warning,'muted'));
   for(const file of row.files||[]){const outcome=file.outcome,section=node('section',undefined,'nfo-export-file'),destination=file.name?(file.directory+'/'+file.name):'No destination';section.append(node('h3',(file.kind==='nfo'?'NFO':file.kind)+' · '+(outcome?.state||file.action)),node('p',destination,'muted'));if(file.reason||outcome?.reason)section.append(node('p',file.reason||outcome.reason,'muted'));if(file.sha256)section.append(node('p',(file.source||'Reviewed source')+' · SHA-256 '+file.sha256+' · '+file.bytes+' bytes','muted'));if(file.existing)section.append(node('p','Existing SHA-256 '+file.existing.sha256,'muted'));if(outcome?.retention)section.append(node('p','Retained originals: '+file.directory+'/'+outcome.retention,'muted'));if(file.format)section.append(node('p',file.format.extension.toUpperCase()+' · '+file.format.width+' × '+file.format.height,'muted'));
    if(reviewing&&file.action==='update'){const label=node('label'),update=node('input');update.type='checkbox';update.checked=updates.has(row.asset);update.disabled=!selected.has(row.asset);updateControl=update;update.setAttribute('aria-label','Approve existing NFO update for '+row.title);update.onchange=()=>update.checked?updates.add(row.asset):updates.delete(row.asset);label.append(update,node('span','Update this Curator-written NFO and retain the original'));section.append(label);}
    if(file.kind==='nfo'&&file.content){const values=node('details');values.append(node('summary','Metadata and XML preview'));for(const change of row.differences||[]){const diff=node('section',undefined,'nfo-export-file');diff.append(node('h4',change.field),node('p','Before: '+(change.before.join('; ')||'(empty)'),'muted'),node('p','After: '+(change.after.join('; ')||'(empty)'),'muted'));values.append(diff);}if(row.previous_nfo){values.append(node('h4','Existing NFO'),node('pre',row.previous_nfo));}values.append(node('h4','Proposed supported values'),node('pre',JSON.stringify(row.field_values,null,2)),node('h4','Proposed NFO'),node('pre',file.content));section.append(values);}box.append(section);
   }list.append(box);
  }
  pages.replaceChildren();if(record.items.length>25){const previous=button('Previous',()=>{page--;render();},'text-button'),next=button('Next',()=>{page++;render();},'text-button');previous.disabled=page===0;next.disabled=(page+1)*25>=record.items.length;pages.append(previous,node('span','Page '+(page+1)+' of '+Math.ceil(record.items.length/25)),next);}
 }
 render();actions.append(button('Close',()=>closeInspector(),'subtle'));
 if(reviewing){actions.append(button('Clear selection',()=>{selected.clear();updates.clear();render();approve.disabled=true;},'text-button'),approve);approve.disabled=!selected.size;}
 else if(record.phase==='queued')detail.append(node('p','Queued in File operations. Use the queue controls to run or pause it.','muted'));
 else {const failed=record.items.filter(r=>['failed','blocked','partial'].includes(r.phase)||['interrupted','cancelled'].includes(record.phase)&&r.phase==='ready').map(r=>r.asset);if(failed.length)actions.append(button('Prepare retry',()=>openNfoExport(failed,record.library),'text-button'));}
 if(record.phase==='running'||record.phase==='queued'){actions.append(button('Refresh outcomes',()=>openNfoManifest(record.id),'text-button'));}
}
