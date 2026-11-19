'use strict';
let metadataDraft=null;
function metadataDisplay(value){return Array.isArray(value)?value.map(v=>typeof v==='object'?v.name+(v.role?' — '+v.role:''):v).join(', '):String(value??'');}
async function openMetadataManager(tasks,restored=null){
 if(!tasks.length||!prepareInspector())return;
 const refs=tasks.map(t=>({id:t.id,version:t.version})),assets=tasks.map(t=>catalogIndex().byId.get(t.asset)),single=tasks.length===1,token='metadata:'+clientId();
 inspectorMode='metadata-manager';openedTask=token;selectedAssetId=assets[0]?.id;
 $('task-kind').textContent=single?'METADATA':'BULK METADATA';$('task-title').textContent=single?fileName(assets[0]):'Edit '+tasks.length+' selected files';$('task-reason').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();showInspector();
 if(tasks.some(t=>['queued','running','publishing'].includes(t.status))){detail.append(node('p','Metadata work is already queued or running for a selected item. Review its progress in Queue before changing it.','muted'));actions.append(button('Close',()=>closeInspector(),'subtle'));return;}
 detail.append(node('p','Only checked fields will change. Artwork is managed separately.','muted'));
 const scope=node('details',undefined,'manager-scope');scope.append(node('summary','Selected files ('+tasks.length+')'),...assets.map(a=>node('p',fileName(a),'muted')));detail.append(scope);
 let current=assets[0]?.item||{};
 if(single)try{current=(await api('metadata/read?'+new URLSearchParams({id:tasks[0].id}))).item||current;}catch(error){detail.append(node('p','Showing cached metadata: '+error.message,'error'));}
 if(openedTask!==token)return;
 if(!restored&&single&&Object.keys(tasks[0].plan?.changes||{}).length){restored={};for(const [key,value] of Object.entries(tasks[0].plan.changes))if(key!=='label')restored[key]=['genre','collection'].includes(key)?{mode:'replace',values:value}:value;}
 const initial={title:current.title||'',summary:current.summary||'',studio:current.studio||'',tagline:current.tagline||'',genre:(current.Genre||[]).map(x=>x.tag),collection:(current.Collection||[]).map(x=>x.tag)},controls=new Map();
 const note=node('p','','muted');note.setAttribute('role','status');const preview=button('Preview changes',previewChanges,'primary');preview.disabled=true;
 function changed(){inspectorDirty=[...controls.values()].some(c=>c.use.checked)||useCast.checked;preview.disabled=!inspectorDirty;note.textContent=inspectorDirty?'Unchecked fields are kept unchanged.':'Choose a field to edit.';}
 for(const [key,label] of [['studio','Studio / creator'],['genre','Categories'],['collection','Collections'],['summary','Description'],['title','Title'],['tagline','Tagline']]){
  const row=node('section',undefined,'manager-field'),use=node('input');use.type='checkbox';use.setAttribute('aria-label','Change '+label);const heading=node('label',undefined,'checkbox-label');heading.append(use,document.createTextNode(' '+label));row.append(heading);
  const input=node(key==='summary'?'textarea':'input'),mode=node('select');input.setAttribute('aria-label',label);if(key==='summary')input.rows=4;
  if(['genre','collection'].includes(key)){
   for(const [value,text] of [['add','Add to existing'],['replace','Replace existing'],['clear','Clear existing']]){const option=node('option',text);option.value=value;mode.append(option);}mode.setAttribute('aria-label',label+' action');mode.value=single?'replace':'add';row.append(mode,input,collectionPicker(input,tasks[0].library,single?initial[key]:[],()=>{use.checked=true;changed();},false,key));
   mode.onchange=()=>{use.checked=true;input.collectionPicker.setDisabled(mode.value==='clear');changed();};
  }else{input.value=single?initial[key]:'';row.append(input);input.oninput=()=>{use.checked=true;changed();};}
  use.onchange=changed;controls.set(key,{use,input,mode});
  if(!single&&['title','tagline'].includes(key)){let advanced=detail.querySelector('.metadata-advanced');if(!advanced){advanced=node('details',undefined,'metadata-advanced');advanced.append(node('summary','Additional shared fields'),node('p','A checked title or description will be the same for every selected file.','muted'));detail.append(advanced);}advanced.append(row);}else detail.append(row);
 }
 const castBox=node('section',undefined,'manager-cast'),useCast=node('input');useCast.type='checkbox';useCast.setAttribute('aria-label','Apply shared cast');const castLabel=node('label',undefined,'checkbox-label');castLabel.append(useCast,document.createTextNode(single?' Change cast names, roles and order':' Apply this cast to all '+tasks.length+' files'));castBox.append(node('h3','Cast'),castLabel,node('p','Checked cast replaces the credits in the order shown. An empty checked list clears credits. Existing portraits are preserved for matching credits.','muted'));
 const people=node('div'),castRows=[];
 function addPerson(name='',role=''){
  const row=node('div',undefined,'manager-credit'),nameInput=node('input'),roleInput=node('input');nameInput.value=name;nameInput.setAttribute('aria-label','Person name');roleInput.value=role;roleInput.setAttribute('aria-label','Person role');const entry={row,name:nameInput,role:roleInput};castRows.push(entry);
  const move=direction=>{const i=castRows.indexOf(entry),j=i+direction;if(j<0||j>=castRows.length)return;[castRows[i],castRows[j]]=[castRows[j],castRows[i]];people.replaceChildren(...castRows.map(r=>r.row));useCast.checked=true;changed();};
  row.append(nameInput,roleInput,button('↑',()=>move(-1),'text-button'),button('↓',()=>move(1),'text-button'),button('Remove',()=>{castRows.splice(castRows.indexOf(entry),1);row.remove();useCast.checked=true;changed();},'text-button'));nameInput.oninput=roleInput.oninput=()=>{useCast.checked=true;changed();};people.append(row);
 }
 if(single)(current.Role||[]).forEach(p=>addPerson(p.tag,p.role||''));
 useCast.onchange=changed;castBox.append(people,button('+ Add person',()=>{addPerson();useCast.checked=true;changed();},'text-button'));detail.append(castBox);
 const saved=node('select');saved.setAttribute('aria-label','Add saved person');saved.append(node('option','Choose an existing person…'));saved.options[0].value='';
 try{const profiles=(await api('cast/profiles')).profiles||[];if(openedTask!==token)return;for(const p of profiles){const option=node('option',p.name);option.value=p.id;saved.append(option);}saved.onchange=()=>{const p=profiles.find(p=>p.id===saved.value);if(p){addPerson(p.name);useCast.checked=true;changed();saved.value='';}};castBox.append(saved);}catch(error){castBox.append(node('p','Saved people unavailable: '+error.message,'muted'));}
 function fields(){const values={};for(const [key,c] of controls)if(c.use.checked)values[key]=['genre','collection'].includes(key)?{mode:c.mode.value,values:c.mode.value==='clear'?[]:metadataListValue(c.input)}:c.input.value;if(useCast.checked)values.cast=castRows.map(p=>({name:p.name.value.trim(),role:p.role.value}));return values;}
 if(restored){for(const [key,value] of Object.entries(restored)){if(key==='cast'){people.replaceChildren();castRows.length=0;value.forEach(p=>addPerson(p.name,p.role));useCast.checked=true;}else{const c=controls.get(key);c.use.checked=true;if(['genre','collection'].includes(key)){c.mode.value=value.mode;c.input.collectionPicker.setValues(value.values);}else c.input.value=value;}}}
 metadataDraft={refs,fields,assets:assets.map(a=>a.id)};
 castBox.append(button('Manage portraits → Artwork',()=>{const draft=fields();metadataDraft={refs,fields:draft,assets:assets.map(a=>a.id)};inspectorDirty=false;return openArtworkManager(assets,{returnMetadata:{tasks,draft},people:true});},'text-button'),node('p','Portraits belong to people. Your metadata draft is kept when opening Artwork.','muted'));
 actions.append(note,button('Cancel',()=>{if(prepareInspector()){metadataDraft=null;closeInspector(true);}},'subtle'),preview);changed();
 async function previewChanges(){
  preview.disabled=true;note.textContent='Reading selected metadata and preparing exact changes…';
  try{const values=fields(),receipt=await api('metadata/preview',{tasks:refs,fields:values});if(openedTask!==token)return;showMetadataPreview(receipt,()=>openMetadataManager(tasks,values));}catch(error){note.textContent=error.message;preview.disabled=false;}
 }
}
function showMetadataPreview(receipt,back){
 const detail=$('task-detail'),actions=$('task-buttons');inspectorDirty=false;detail.replaceChildren();actions.replaceChildren();
 const changed=receipt.rows.filter(r=>Object.keys(r.changes).length),note=node('p',changed.length+' of '+receipt.rows.length+' selected items will change. Nothing has been sent to Plex.','muted');detail.append(note);let page=0;
 const pager=node('div',undefined,'bulk-group-actions'),rows=node('div');detail.append(pager,rows);
 const labels={genre:'Categories',collection:'Collections',summary:'Description',cast:'Cast',studio:'Studio / creator',title:'Title',tagline:'Tagline'};
 function renderPage(){pager.replaceChildren(button('Previous',()=>{page=Math.max(0,page-1);renderPage();},'text-button'),node('span','Page '+(page+1)+' of '+Math.max(1,Math.ceil(receipt.rows.length/25))),button('Next',()=>{page=Math.min(Math.ceil(receipt.rows.length/25)-1,page+1);renderPage();},'text-button'));rows.replaceChildren();for(const row of receipt.rows.slice(page*25,page*25+25)){const box=node('section',undefined,'metadata-preview-item');box.append(node('h3',row.title));if(!Object.keys(row.changes).length)box.append(node('p','No changes','muted'));for(const [field,value] of Object.entries(row.changes)){box.append(node('strong',labels[field]),node('p','Before: '+(metadataDisplay(row.before[field])||'(empty)'),'muted'),node('p','After: '+(metadataDisplay(value)||'(empty)')));}rows.append(box);}}
 renderPage();const status=node('p','','muted'),approve=button('Approve & queue '+changed.length+' changes',async()=>{
  approve.disabled=true;status.textContent='Queueing the reviewed changes…';try{const result=await api('metadata/approve-preview',{id:receipt.id});metadataDraft=null;await refresh();closeInspector(true);toast(result.tasks.length+' metadata jobs queued. Open Queue to start them.');}catch(error){status.textContent=error.message;approve.disabled=false;}
 },'primary');approve.disabled=!changed.length;actions.append(status,button('Back to edit',back,'subtle'),approve);
}
