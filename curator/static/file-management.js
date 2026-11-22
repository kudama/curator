'use strict';
// File selection is separate from task approval and never starts an operation.
const fileManagementSelection=new Set();
function fileManagementFiles(){return libraryFiles().filter(matchesSearch);}
function selectedManagementFiles(){
 const files=libraryFiles(),valid=new Set(files.map(a=>a.id));for(const id of fileManagementSelection)if(!valid.has(id))fileManagementSelection.delete(id);
 return files.filter(a=>fileManagementSelection.has(a.id));
}
function fileManagementSelectionText(){const selected=selectedManagementFiles(),visible=new Set(fileManagementFiles().map(a=>a.id)),hidden=selected.filter(a=>!visible.has(a.id)).length;return selected.length?selected.length+' selected'+(hidden?' · '+hidden+' hidden by search':''):'Choose a file to rename, or select files to join or group. Preview changes before queueing.';}
function chooseFileManagementLibrary(id){
 if(id===libraryId)return true;if(!state.libraries.some(l=>l.id===id)||!prepareInspector())return false;
 closeInspector(true);libraryId=id;selectedAssetId=null;fileManagementSelection.clear();searchText='';$('file-search').value='';render();return true;
}
async function openFileManagement(id=null){
 const asset=id?catalogIndex().byId.get(id):null;
 if(!setScreen('filemanagement'))return;
 if(asset){if(!chooseFileManagementLibrary(asset.library))return;fileManagementSelection.clear();fileManagementSelection.add(id);render();await launchFileManagement('rename');}
}
function renderFileManagementControls(){
 const label=$('file-management-library-control'),select=$('file-management-library'),actions=$('file-management-actions');
 label.hidden=actions.hidden=screen!=='filemanagement';if(label.hidden)return;
 const signature=JSON.stringify(state.libraries.map(l=>[l.id,l.title]));if(select.dataset.libraries!==signature){select.replaceChildren();for(const library of state.libraries){const option=node('option',library.title);option.value=library.id;select.append(option);}select.dataset.libraries=signature;}select.value=libraryId;
 const files=selectedManagementFiles();actions.replaceChildren();
 actions.append(button('Generate NFO files',()=>openNfoExport(),'text-button'));
 for(const [kind,title,min,max] of [['rename','Rename file',1,1],['join','Join parts',2,Infinity],['group','Collection / playlist',1,Infinity]]){
  const control=button(title,()=>launchFileManagement(kind),'text-button');control.disabled=files.length<min||files.length>max;
  control.title=kind==='rename'?'Select one file':kind==='join'?'Select at least two files in this library':'Select files in this library';actions.append(control);
 }
 if(files.length)actions.append(button('Clear selection',()=>{if(!prepareInspector())return;closeInspector(true);fileManagementSelection.clear();render();},'text-button'));
}
async function launchFileManagement(kind){
 const files=selectedManagementFiles();if(!['rename','join','group'].includes(kind)||!files.length||kind==='rename'&&files.length!==1||kind==='join'&&files.length<2)return;
 if(!prepareInspector())return;selectedAssetId=files[0].id;
 await openFileOperation(files[0],kind,files.map(a=>a.id));
}
function renderFileManagement(){
 return fileManagementFiles().map(asset=>{
  const row=node('article',undefined,'file-tool-row'),check=node('input');check.type='checkbox';check.checked=fileManagementSelection.has(asset.id);check.setAttribute('aria-label','Select file '+fileName(asset));
  check.onchange=()=>{if(!prepareInspector()){render();return;}closeInspector(true);check.checked?fileManagementSelection.add(asset.id):fileManagementSelection.delete(asset.id);render();};
  const text=node('div',undefined,'file-tool-name'),name=button(fileName(asset),async()=>{if(!prepareInspector())return;fileManagementSelection.clear();fileManagementSelection.add(asset.id);render();await launchFileManagement('rename');},'text-button');
  text.append(name,node('p',(asset.plex_path||asset.local_path||'').split('/').slice(0,-1).join('/')||'Folder unavailable','muted'));if(asset.availability_error||asset.blocked)text.append(node('p',asset.availability_error||asset.blocked,'error'));
  row.classList.toggle('selected',fileManagementSelection.has(asset.id));row.append(check,thumbnail(asset),text,node('span',formatBytes(asset.fingerprint?.size),'muted'));return row;
 });
}
async function openGroupedTask(assetId,kind){
 const asset=catalogIndex().byId.get(assetId);if(!asset)return;
 const rows=attentionTasks(asset).filter(t=>t.kind===kind&&!t.deleted);
 if(rows.length===1)return openTask(rows[0].id);
 if(rows.length>1)return openAssetOverview(assetId);
 await refresh();toast('This task changed. The list has been refreshed.');
}
