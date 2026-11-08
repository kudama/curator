'use strict';
let state={libraries:[],assets:[],tasks:[],config:{}},libraryId=null,filter='all',selected=new Set(),openedTask=null;
const expandedFiles=new Set();let queueStatus='all',activeGrouping='folder';let screen='library',libraryView='attention',searchText='',selectedAssetId=null,inspectorMode=null,inspectorDirty=false;
const TASK_LABELS={upscale:'Upscale video',optimize:'Optimize encoding',home:'Home-movie analysis',metadata:'Metadata & artwork',inspect:'File access',playlist:'Viewing order',rename:'Rename file',join:'Join parts',group:'Collection & playlist',folder_metadata:'Folder metadata'};
const $=id=>document.getElementById(id);
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
function toast(text,error=false){const feedback=$($('config-dialog').open?'config-feedback':'task-feedback');if(feedback&&(inspectorOpen()||$('config-dialog').open)){feedback.hidden=false;feedback.textContent=text;feedback.className=error?'artwork-status error':'artwork-status';}$('toast').textContent=text;$('toast').className=error?'error':'';$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,7000);}
async function api(path,data){const r=await fetch('/api/'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json','X-Curator-Request':'1'}:{},body:data?JSON.stringify(data):undefined});const value=await r.json();if(!r.ok)throw Error(value.error||'Request failed');return value;}
async function run(fn){try{return await fn();}catch(e){toast(e.message,true);}}
async function refresh(){state=await api('state');if(!libraryId&&state.libraries.length)libraryId=state.libraries[0].id;render();}
function current(){return state.libraries.find(x=>x.id===libraryId);}
const COMPLETED_TASK_STATES=new Set(['applied','resolved']);
const HISTORY_TASK_STATES=new Set(['applied','resolved','rejected','cancelled']);
let catalogCache=null;
function catalogIndex(){
 if(catalogCache?.assets===state.assets&&catalogCache?.tasks===state.tasks)return catalogCache;
 const byId=new Map(state.assets.map(a=>[a.id,a])),byMovie=new Map(),byAsset=new Map();
 for(const a of state.assets){if(a.present===false)continue;const key=a.library+':'+(a.rating_key||a.id);if(!byMovie.has(key))byMovie.set(key,[]);byMovie.get(key).push(a.id);}
 for(const t of state.tasks){if(!byAsset.has(t.asset))byAsset.set(t.asset,[]);byAsset.get(t.asset).push(t);}
 return catalogCache={assets:state.assets,tasks:state.tasks,byId,byMovie,byAsset};
}
function movieTasks(asset){const index=catalogIndex(),ids=index.byMovie.get(asset.library+':'+(asset.rating_key||asset.id))||[];return ids.flatMap(id=>index.byAsset.get(id)||[]).filter(t=>!['playlist','group'].includes(t.kind));}
function movieCompleted(asset){const tasks=movieTasks(asset);return tasks.length>0&&tasks.every(t=>COMPLETED_TASK_STATES.has(t.status));}
function taskAvailable(t){return (['playlist','group'].includes(t.kind)?t.plan?.assets||[t.asset]:[t.asset]).some(id=>catalogIndex().byId.get(id)?.present!==false&&catalogIndex().byId.has(id));}
function visible(){const ids=new Set(workspaceFiles().map(a=>a.id));return state.tasks.filter(t=>t.library===libraryId&&(screen==='library'?ids.has(t.asset)&&(libraryView==='completed'?COMPLETED_TASK_STATES.has(t.status):!HISTORY_TASK_STATES.has(t.status)):screen==='history'?HISTORY_TASK_STATES.has(t.status):['queued','running','publishing','awaiting_review','blocked','failed'].includes(t.status)));}
function button(text,fn,cls){const b=node('button',text,cls);b.type='button';b.onclick=()=>run(fn);return b;}
function formatBytes(bytes){
 if(!Number.isFinite(bytes)||bytes<0)return 'Unavailable';
 const units=['B','KiB','MiB','GiB','TiB'];let value=bytes,index=0;while(value>=1024&&index<units.length-1){value/=1024;index++;}return value.toLocaleString(undefined,{maximumFractionDigits:index?2:0})+' '+units[index];
}
function sizeChange(source,output){
 if(!Number.isFinite(source)||!Number.isFinite(output)||source<=0||output<0)return 'Size change unavailable';
 const difference=source-output;if(!difference)return 'Same size';
 return (difference>0?'Saved ':'Larger by ')+formatBytes(Math.abs(difference))+' ('+(Math.abs(difference)/source*100).toFixed(1)+'%)';
}
function sizeComparison(t,asset){
 const original=t.source?.size??asset?.technical?.size_bytes??asset?.fingerprint?.size,processed=t.result?.size_bytes;
 const box=node('section',undefined,'size-comparison');box.append(node('h3','File size'));
 const grid=node('dl');for(const [label,value] of [['Original',original],['Processed',processed]]){const pair=node('div');pair.append(node('dt',label),node('dd',formatBytes(value)));grid.append(pair);}box.append(grid,node('p',sizeChange(original,processed),'size-change'));return box;
}
function progressView(t){
 const box=node('div',undefined,'task-progress'),label=node('span'),bar=node('progress');box.dataset.progressTask=t.id;bar.setAttribute('aria-label','Task progress');box.append(label,bar);updateProgressView(box,t);return box;
}
function etaLabel(seconds){const minutes=Math.ceil(Math.max(0,seconds)/60);if(minutes<1)return 'under a minute';if(minutes<60)return minutes+'m';return Math.floor(minutes/60)+'h'+(minutes%60?' '+minutes%60+'m':'');}
function updateProgressView(box,t){
 box.hidden=!['running','publishing'].includes(t.status);if(box.hidden)return;
 const p=t.progress||{},label=box.querySelector('span'),bar=box.querySelector('progress');
 label.textContent=p.phase||(t.status==='publishing'?'Publishing video':'Processing video');
 if(Number.isFinite(p.percent)){
  bar.max=100;bar.value=Math.max(0,Math.min(100,p.percent));label.textContent+=' · '+bar.value.toFixed(1)+'%';
  if(p.pass_count>1)label.textContent+=' · pass '+p.pass_number+'/'+p.pass_count;
  if(Number.isFinite(p.fps))label.textContent+=' · '+p.fps.toFixed(1)+' fps';
  label.textContent+=Number.isFinite(p.eta_seconds)?' · Encode ETA ≈ '+etaLabel(p.eta_seconds-Math.max(0,Date.now()/1000-(p.eta_updated_at||Date.now()/1000))):' · Estimating encode ETA…';
 }else if(Number.isFinite(p.total_bytes)&&p.total_bytes>0&&Number.isFinite(p.completed_bytes)){
  bar.max=p.total_bytes;bar.value=Math.min(p.completed_bytes,p.total_bytes);label.textContent+=' · '+formatBytes(p.completed_bytes)+' / '+formatBytes(p.total_bytes)+' · '+Math.min(100,p.completed_bytes/p.total_bytes*100).toFixed(0)+'%';
 }else{bar.removeAttribute('value');if(Number.isFinite(p.output_bytes))label.textContent+=' · '+formatBytes(p.output_bytes)+' written';if(p.phase==='Processing video')label.textContent+=' · Estimating encode ETA…';}
}
function localPath(value){
 let path=value.trim();
 if(path.length>=2&&((path.startsWith("'")&&path.endsWith("'"))||(path.startsWith('"')&&path.endsWith('"'))))path=path.slice(1,-1);
 if(path&&!path.startsWith('/'))throw Error('Use the mounted Mac folder path, starting with /Volumes/ or /. Wrapping quotes are removed automatically.');
 return path;
}
const ARTWORK_LABELS={cover:'Cover',background:'Background',logo:'Logo',square:'Square art'};
function artworkFormat(profile,kind){if(kind==='logo')return {ratio:null,size:'Original proportions · transparent PNG recommended'};if(kind==='square')return {ratio:'1:1',size:'1000 × 1000'};return kind==='background'||profile==='home'?{ratio:'16:9',orientation:'landscape',size:'1920 × 1080'}:{ratio:'2:3',orientation:'portrait',size:'1000 × 1500'};}
function coverPrompt(title,preset,profile,kind,creator='',logo=false){
 const format=artworkFormat(profile,kind);
 return `Create an exact ${format.ratio} ${format.orientation} ${kind} at ${format.size} pixels. Use the supplied frame as reference; preserve its proportions and never stretch it.\n\n${preset.details}\n\nBlend the upper image smoothly into ${preset.background}. Keep one integrated composition without a rectangular inset or frame.\n\n${kind==='cover'?`Title: ${title}. ${preset.typography} Keep it readable at Plex thumbnail size.`:'Leave quiet space for Plex overlays. Omit video titles and captions.'}${creator?`\n\nCreator branding: ${creator}.`:''}${logo?' Use the separately supplied creator logo faithfully, preserving its proportions and lettering.':''}`;
}
function portraitVideo(asset){
 const media=asset?.technical;if(!media)return false;
 const video=(media.streams||[]).find(s=>s.codec_type==='video'&&!s.disposition?.attached_pic)||{};
 const ratio=value=>{const parts=String(value||'').split(':').map(Number);return parts.length===2&&parts[0]>0&&parts[1]>0?parts[0]/parts[1]:null;};
 const sar=ratio(video.sample_aspect_ratio),dar=ratio(video.display_aspect_ratio);
 let width=Number(media.width)*(sar||1),height=Number(media.height);if(!sar&&dar)width=height*dar;
 const rotation=Number((video.side_data_list||[]).find(r=>r.rotation!==undefined)?.rotation??video.tags?.rotate??0);
 if(Math.abs(rotation)%180===90)[width,height]=[height,width];return height>width;
}
function canQueue(t){return taskAvailable(t)&&!catalogIndex().byId.get(t.asset)?.availability_error&&['recommendation','failed','blocked','cancelled'].includes(t.status)&&!['inspect','folder_metadata'].includes(t.kind)&&(t.kind!=='metadata'||Object.keys(t.plan.changes||{}).length>0)&&(t.kind!=='optimize'||Boolean(t.plan.handbrake_preset))&&(t.kind!=='upscale'||Boolean(state.config.topaz_filter))&&!catalogIndex().byId.get(t.asset)?.blocked;}
function selectionVisible(){return ['all','recommendation'].includes(filter)||$('library-tools').open;}
function renderSelection(){
 const rows=visible(),chosen=rows.filter(t=>selected.has(t.id)),eligible=chosen.filter(canQueue);
 $('selection-controls').hidden=!selectionVisible();$('queue-selected').hidden=!['all','recommendation'].includes(filter);
 $('queue-selected').disabled=!eligible.length;$('queue-selected').textContent=eligible.length?`Queue selected (${eligible.length})`:'Queue selected';
 $('select-all').checked=rows.length>0&&chosen.length===rows.length;$('select-all').indeterminate=chosen.length>0&&chosen.length<rows.length;
 $('select-all').disabled=!rows.length;$('export-kometa').disabled=!current()||!chosen.length;
 $('selection-note').textContent=['all','recommendation'].includes(filter)&&chosen.length>eligible.length?'Some selected tasks need tool settings, a proposal or file access resolved before queueing.':'';
}
async function fileBase64(file){const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(const b of bytes)binary+=String.fromCharCode(b);return btoa(binary);}
function artworkEditor(t,profile,kind,markDirty){
 const section=node('section',undefined,'artwork-card'),format=artworkFormat(profile,kind);
 section.append(node('h3',ARTWORK_LABELS[kind]),node('p',(format.ratio?format.ratio+' · ':'')+format.size,'muted'));
 const current=node('img');current.alt='Current '+ARTWORK_LABELS[kind].toLowerCase();current.className='editor-image';if(format.ratio)current.style.aspectRatio=format.ratio.replace(':',' / ');if(kind==='logo')current.classList.add('logo-preview');
 const missing=node('p','No current '+ARTWORK_LABELS[kind].toLowerCase()+' available','muted');missing.hidden=true;
 const reload=()=>{missing.hidden=true;current.hidden=false;current.src='/api/artwork/image?'+new URLSearchParams({id:t.id,kind,v:Date.now()});};
 current.onerror=()=>{current.hidden=true;missing.hidden=false;};reload();section.append(current,missing);
 const label=node('label','Choose replacement '+ARTWORK_LABELS[kind].toLowerCase()),file=node('input');file.type='file';file.accept='image/jpeg,image/png';label.append(file);
 const preview=node('img');preview.alt='Replacement '+ARTWORK_LABELS[kind].toLowerCase()+' preview';preview.className='editor-image';if(format.ratio)preview.style.aspectRatio=format.ratio.replace(':',' / ');if(kind==='logo')preview.classList.add('logo-preview');preview.hidden=true;
 const status=node('p','','muted');let url=null,ready=false;
 const clear=()=>{file.value='';ready=false;preview.hidden=true;status.textContent='';if(url)URL.revokeObjectURL(url);url=null;};
 file.onchange=()=>{if(url)URL.revokeObjectURL(url);ready=false;preview.hidden=true;const image=file.files[0];status.textContent='';if(image){if(image.size>10*1024*1024){status.textContent='Choose a JPEG/PNG under 10 MiB.';}else{url=URL.createObjectURL(image);preview.src=url;preview.hidden=false;status.textContent='Loading replacement preview…';}}markDirty();};
 preview.onload=()=>{ready=true;status.textContent=`Replacement ready · ${preview.naturalWidth} × ${preview.naturalHeight}`+(kind==='square'&&preview.naturalWidth!==preview.naturalHeight?' · Not square; Plex may crop the display.':'');markDirty();};
 preview.onerror=()=>{ready=false;status.textContent='This image could not be decoded. Choose a valid JPEG or PNG.';markDirty();};
 section.append(label,preview,status);
 return {section,file,ready:()=>ready,clear,reload};
}
async function castEditor(t,item,markDirty,options={}){
 const section=node('section',undefined,'cast-editor');section.append(node('h3','Cast'));
 section.append(node('p',options.folder?'Choose the cast shared by this folder. Reuse saved profiles or add names and pictures.':'Add names, roles and profile pictures. Save changes applies this title only. Remember a profile to reuse its name and photo on another title.','muted'));
 let profiles=[],baseline='',rows=[];
 try{profiles=(await api('cast/profiles')).profiles||[];}catch(error){section.append(node('p','Saved profiles unavailable: '+error.message,'muted'));}
 const tools=node('div',undefined,'cast-tools'),saved=node('select');saved.setAttribute('aria-label','Add saved cast member');
 const updateProfiles=()=>{saved.replaceChildren();const first=node('option','Add saved cast member…');first.value='';saved.append(first);for(const profile of profiles){const option=node('option',profile.name);option.value=profile.id;saved.append(option);}saved.disabled=!profiles.length;};updateProfiles();
 const list=node('div');tools.append(saved,button('Add person',()=>{add({name:'',role:'',thumb:''},true);markDirty();}));section.append(tools,list);
 const values=()=>rows.map(row=>({name:row.name.value,role:row.role.value,thumb:row.data.thumb||'',profile_id:row.data.profile_id||null,revision:row.data.revision||null,remember:row.remember.checked,clear_photo:row.clear.checked,file:row.file.files[0]?row.file.files[0].name+':'+row.file.files[0].size+':'+row.file.files[0].lastModified:null}));
 const changed=()=>JSON.stringify(values())!==baseline;
 const move=(row,delta)=>{const at=rows.indexOf(row),next=at+delta;if(next<0||next>=rows.length)return;[rows[at],rows[next]]=[rows[next],rows[at]];list.replaceChildren(...rows.map(r=>r.card));markDirty();};
 function add(data,isNew=false,index=null){
  const matched=!data.profile_id?profiles.find(p=>p.name===data.name):null;if(matched)data={...data,profile_id:matched.id,revision:matched.revision};
  const row={data:{...data}},card=node('div',undefined,'cast-row');row.card=card;
  const picture=node('img');picture.className='cast-picture';picture.alt='Cast profile picture';picture.hidden=!data.thumb&&!data.has_photo&&!data.photo;if(!picture.hidden)picture.src=data.photo?'/api/folders/image?'+new URLSearchParams({photo:data.photo}):index===null&&data.profile_id?'/api/cast/image?'+new URLSearchParams({profile:data.profile_id}):'/api/cast/image?'+new URLSearchParams({id:t.id,index:index??0,v:Date.now()});
  const pictureNote=node('span','','muted');picture.onerror=()=>{picture.hidden=true;pictureNote.textContent='Picture unavailable';};card.append(picture);
  const fields=node('div',undefined,'cast-fields');row.name=node('input');row.name.value=data.name||'';row.name.maxLength=500;const nameLabel=node('label','Name');nameLabel.append(row.name);
  row.role=node('input');row.role.value=data.role||'';const roleLabel=node('label','Role (optional)');roleLabel.append(row.role);
  row.file=node('input');row.file.type='file';row.file.accept='image/png,image/jpeg';const fileLabel=node('label','Profile picture');fileLabel.append(row.file);
  row.clear=node('input');row.clear.type='checkbox';const clearLabel=node('label',undefined,'checkbox-label');clearLabel.append(row.clear,document.createTextNode(' Remove photo'));
  row.remember=node('input');row.remember.type='checkbox';row.remember.checked=isNew;const rememberLabel=node('label',undefined,'checkbox-label');rememberLabel.append(row.remember,document.createTextNode(' Remember profile for other titles'));
  fields.append(nameLabel,roleLabel,fileLabel,pictureNote,clearLabel);if(!options.folder)fields.append(rememberLabel);card.append(fields);
  const controls=node('div',undefined,'cast-controls');controls.append(button('Move up',()=>move(row,-1),'subtle'),button('Move down',()=>move(row,1),'subtle'),button('Remove person',()=>{rows=rows.filter(r=>r!==row);card.remove();markDirty();},'subtle'));card.append(controls);
  row.name.oninput=row.role.oninput=row.remember.onchange=()=>markDirty();
  row.file.onchange=()=>{const file=row.file.files[0];pictureNote.textContent='';if(file){if(file.size>10*1024*1024){pictureNote.textContent='Picture must be under 10 MiB';row.file.value='';}else{row.clear.checked=false;const url=URL.createObjectURL(file);picture.src=url;picture.hidden=false;picture.onload=()=>URL.revokeObjectURL(url);}}markDirty();};
  row.clear.onchange=()=>{if(row.clear.checked){row.file.value='';picture.hidden=true;}markDirty();};rows.push(row);list.append(card);
 }
 if(options.rows)options.rows.forEach(r=>add(r));else (item.Role||[]).forEach((r,index)=>add({name:r.tag,role:r.role||'',thumb:r.thumb||''},false,index));baseline=JSON.stringify(values());
 saved.onchange=()=>{const p=profiles.find(p=>p.id===saved.value);if(p){add({name:p.name,role:'',thumb:'',profile_id:p.id,revision:p.revision,has_photo:p.has_photo});saved.value='';markDirty();}};
 async function payload(){const data=[];for(const row of rows){const value={name:row.name.value.trim(),role:row.role.value,thumb:row.data.thumb||'',remember:row.remember.checked,clear_photo:row.clear.checked};if(options.folder&&row.data.photo)value.photo=row.data.photo;if(row.data.profile_id){value.profile_id=row.data.profile_id;value.revision=row.data.revision;}if(row.file.files[0])value.image=await fileBase64(row.file.files[0]);data.push(value);}return data;}
 function accept(result){profiles=result.profiles;updateProfiles();rows.forEach((row,index)=>{row.data={...result.cast[index]};const profile=profiles.find(p=>p.name===row.data.name);if(profile){row.data.profile_id=profile.id;row.data.revision=profile.revision;}row.file.value='';row.clear.checked=false;row.remember.checked=false;});baseline=JSON.stringify(values());}
 return {section,changed,payload,accept};
}
async function openFileEditor(t,asset){
 openedTask=t.id;$('task-kind').textContent='METADATA & ARTWORK';$('task-title').textContent=(asset.plex_path||'').split('/').pop()||asset.title;$('task-reason').hidden=true;$('task-feedback').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();
 const status=node('p','Loading current details…','editor-status');status.setAttribute('role','status');actions.append(status);
 const cancel=button('Cancel',()=>{closeInspector(true);}),save=button('Save changes',saveChanges,'primary');save.disabled=true;actions.append(cancel,save);showInspector();
 let loading=true,promptReady=false,busy=false,brandingDirty=false,brandingInfo=null,brandingError=false,original={},preset=null,useFolder=null,remember=null,folder=null,creator=null,logo=null,fields={},artworks={},castUI=null,promptEdited=false;
 const readOnly=['queued','running','publishing'].includes(t.status);const profile=state.libraries.find(l=>l.id===t.library)?.profile||'commercial';
 const presets=state.config.branding_presets||[];
 const same=value=>JSON.stringify(Array.isArray(value)?[...value].sort():value);
 const readChanges=()=>Object.fromEntries(Object.entries(fields).map(([key,input])=>[key,Array.isArray(original[key])?metadataListValue(input):input.value]).filter(([key,value])=>same(value)!==same(original[key])));
 function markDirty(){if(busy)return;if(loading){inspectorDirty=true;return;}if(readOnly){inspectorDirty=false;save.disabled=true;status.textContent='This task is '+t.status+'. Remove it from Processing before editing.';return;}const invalid=Object.values(artworks).some(a=>a.file.files.length&&!a.ready()),dirty=Object.keys(readChanges()).length||Object.values(artworks).some(a=>a.file.files.length)||brandingDirty||castUI?.changed();inspectorDirty=Boolean(dirty);save.disabled=!dirty||invalid;status.textContent=invalid?'A replacement image is not ready.':dirty?'Unsaved changes':'No pending changes';}
 let item=asset.item;
 try{item=(await api('metadata/read?'+new URLSearchParams({id:t.id}))).item||item;}catch(error){detail.append(node('p','Showing cached metadata: '+error.message,'muted'));}
 if(!inspectorOpen()||openedTask!==t.id)return;
 original={title:item.title||'',summary:item.summary||'',studio:item.studio||'',tagline:item.tagline||'',genre:(item.Genre||[]).map(x=>x.tag),label:(item.Label||[]).map(x=>x.tag),collection:(item.Collection||[]).map(x=>x.tag)};
 const changes=t.status==='applied'?{}:t.plan.changes||{},suggested=t.kind==='home'&&t.status!=='applied'?t.result:null;
 const metadata=node('section',undefined,'metadata-editor');metadata.append(node('h3','Details'));const grid=node('div',undefined,'metadata-grid');
 for(const [key,label] of [['title','Title'],['summary','Description'],['studio','Studio'],['tagline','Tagline'],['genre','Tags / genres'],['label','Labels'],['collection','Collections']]){const wrap=node(['genre','label','collection'].includes(key)?'div':'label',label,key==='summary'?'full-width':''),input=node(key==='summary'?'textarea':'input');if(key==='summary')input.rows=4;const value=changes[key]??(key==='collection'?[...new Set([...original.collection,...(suggested?.themes||[])])]:suggested?.[key]??original[key]);input.value=Array.isArray(value)?value.join(', '):value;if(Array.isArray(value))input.placeholder='Comma separated';wrap.append(input);grid.append(wrap);fields[key]=input;input.oninput=()=>{markDirty();updatePrompt();};if(['genre','label','collection'].includes(key))wrap.append(collectionPicker(input,t.library,Array.isArray(value)?value:[],markDirty,readOnly,key));}metadata.append(grid);detail.append(metadata);
 castUI=await castEditor(t,item,markDirty);if(!inspectorOpen()||openedTask!==t.id)return;detail.append(castUI.section);
 const artGrid=node('div',undefined,'artwork-grid');for(const kind of Object.keys(ARTWORK_LABELS)){artworks[kind]=artworkEditor(t,profile,kind,markDirty);artGrid.append(artworks[kind].section);}detail.append(artGrid);
 const brandingSection=node('section',undefined,'editor-branding');brandingSection.append(node('h3','Branding'));
 const presetLabel=node('label','Branding preset');preset=node('select');for(const row of presets){const option=node('option',row.name);option.value=row.id;preset.append(option);}presetLabel.append(preset);brandingSection.append(presetLabel);
 let savedLogo=false;
 if(profile==='home'){
  try{brandingInfo=await api('branding?'+new URLSearchParams({id:t.id}));}catch(error){brandingError=true;brandingSection.append(node('p','Folder branding unavailable: '+error.message,'muted'));}
  if(!inspectorOpen()||openedTask!==t.id)return;
  if(brandingInfo){
   const suggested=brandingInfo.suggested||brandingInfo.folders[0],template=suggested?.template||{};
   folder=node('select');for(const row of brandingInfo.folders){const option=node('option',row.folder);option.value=row.folder;folder.append(option);}folder.value=suggested.folder;
   const desired=brandingInfo.preset_override||template.preset_id||template.style;if(presets.some(p=>p.id===desired))preset.value=desired;else if(desired)brandingSection.append(node('p','The saved preset is unavailable. Choose an available preset before saving new branding.','muted'));
   const useLabel=node('label',undefined,'checkbox-label');useFolder=node('input');useFolder.type='checkbox';useFolder.checked=brandingInfo.confirmed&&!brandingInfo.declined;useLabel.append(useFolder,document.createTextNode(' Use this folder’s creator branding'));brandingSection.append(useLabel);
   const rememberLabel=node('label',undefined,'checkbox-label');remember=node('input');remember.type='checkbox';rememberLabel.append(remember,document.createTextNode(' Remember preset for this folder'));brandingSection.append(rememberLabel);
   const defaults=node('details');defaults.append(node('summary','Folder creator & logo'));
   const folderLabel=node('label','Parent folder');folderLabel.append(folder);creator=node('input');creator.value=template.creator||'';const creatorLabel=node('label','Creator');creatorLabel.append(creator);logo=node('input');logo.type='file';logo.accept='image/png,image/jpeg';const logoLabel=node('label','Choose creator logo reference');logoLabel.append(logo);defaults.append(folderLabel,creatorLabel,logoLabel);
   const reference=node('a','Download saved logo for Mage');reference.download='creator-logo';reference.hidden=!template.logo;reference.href='/api/branding/logo?'+new URLSearchParams({id:t.id,folder:folder.value});defaults.append(reference);savedLogo=Boolean(template.logo);
   const brandingChanged=()=>{brandingDirty=true;markDirty();updatePrompt();};
   preset.onchange=brandingChanged;useFolder.onchange=brandingChanged;remember.onchange=brandingChanged;
   creator.oninput=()=>{remember.checked=true;useFolder.checked=true;brandingChanged();};logo.onchange=()=>{remember.checked=true;useFolder.checked=true;brandingChanged();};
   folder.onchange=()=>{const row=brandingInfo.folders.find(r=>r.folder===folder.value),value=row.template||{};creator.value=value.creator||'';logo.value='';savedLogo=Boolean(value.logo);reference.hidden=!value.logo;reference.href='/api/branding/logo?'+new URLSearchParams({id:t.id,folder:folder.value});const id=value.preset_id||value.style;if(presets.some(p=>p.id===id))preset.value=id;useFolder.checked=false;remember.checked=false;brandingChanged();};
   brandingSection.append(defaults);
  }
 }
 if(!brandingInfo)preset.onchange=()=>{updatePrompt();};detail.append(brandingSection);
 const mage=node('details');mage.append(node('summary','Mage prompt (optional)'));const targetLabel=node('label','Artwork for'),target=node('select');for(const value of ['cover','background']){const option=node('option',value==='cover'?'Cover':'Background');option.value=value;target.append(option);}targetLabel.append(target);
 const promptLabel=node('label','Mage prompt'),prompt=node('textarea');prompt.rows=8;promptLabel.append(prompt);const promptNote=node('p','Copy this prompt to Mage and supply a reference frame. Artwork is imported above.','muted');
 function updatePrompt(){if(!promptReady||!preset||!presets.length)return;if(promptEdited){promptNote.textContent='Your prompt edits are preserved. Clear the prompt to regenerate it from your current choices.';return;}const row=presets.find(p=>p.id===preset.value)||presets[0];prompt.value=coverPrompt(fields.title.value,row,profile,target.value,useFolder?.checked?creator.value:'',useFolder?.checked&&(savedLogo||logo.files.length));}
 prompt.oninput=()=>{promptEdited=Boolean(prompt.value);if(!promptEdited)updatePrompt();};target.onchange=updatePrompt;mage.append(targetLabel,promptLabel,promptNote,button('Copy prompt',async()=>{await navigator.clipboard.writeText(prompt.value);promptNote.textContent='Prompt copied.';}));if(t.candidates?.length){const frames=node('div',undefined,'frame-grid');for(const frame of t.candidates){const figure=node('figure'),image=node('img');image.src='/api/frames/'+t.asset+'/'+frame.file;image.alt='Reference frame at '+frame.seconds+' seconds';figure.append(image,node('figcaption',frame.seconds+' seconds · right-click to save for Mage'));frames.append(figure);}mage.append(frames);}
 detail.append(mage);editorTabs(detail,[['Details',[metadata]],['Cast',[castUI.section]],['Artwork',[artGrid]],['Branding',[brandingSection,mage]]]);loading=false;promptReady=true;updatePrompt();markDirty();if(readOnly){for(const control of detail.querySelectorAll('input,select,textarea,button,fieldset'))control.disabled=true;save.hidden=true;cancel.textContent='Close';actions.append(button('View processing',()=>setScreen('processing'),'primary'));}
 async function saveChanges(){
  if(busy)return;busy=true;save.disabled=true;cancel.disabled=true;const close=$('task-dialog').querySelector('[data-close]');close.disabled=true;
  const inputs=[...detail.querySelectorAll('input,select,textarea,button,fieldset')];inputs.forEach(input=>input.disabled=true);const saved=[],errors=[];
  status.textContent='Saving changes…';status.className='editor-status';
  const changes=readChanges();
  if(Object.keys(changes).length){try{const result=await api('metadata/apply',{id:t.id,version:t.version,changes});t.version=result.version;for(const key of Object.keys(changes)){const value=result.metadata?.[key]??changes[key];original[key]=value;if(fields[key].collectionPicker)fields[key].collectionPicker.setValues(value);else fields[key].value=Array.isArray(value)?value.join(', '):value;}updatePrompt();saved.push('details');}catch(error){errors.push('Details: '+error.message);}}
  if(castUI?.changed()){try{const result=await api('cast/apply',{id:t.id,version:t.version,cast:await castUI.payload()});t.version=result.version;castUI.accept(result);saved.push('cast');}catch(error){errors.push('Cast: '+error.message);}}
  for(const [kind,art] of Object.entries(artworks)){if(!art.file.files.length)continue;try{const result=await api('cover/apply',{id:t.id,kind,image:await fileBase64(art.file.files[0])});if(!result.selected)throw Error('Plex did not verify selection');art.clear();art.reload();saved.push(ARTWORK_LABELS[kind].toLowerCase());}catch(error){errors.push(ARTWORK_LABELS[kind]+': '+error.message);}}
  if(brandingDirty&&brandingInfo&&!brandingError){try{const row=brandingInfo.folders.find(r=>r.folder===folder.value),image=logo.files[0];if(image&&image.size>10*1024*1024)throw Error('Logo must be under 10 MiB');const result=await api('branding/choice',{id:t.id,choice:{folder:folder.value,revision:row.revision,preset_id:preset.value,remember:remember.checked,creator:creator.value,use_folder:useFolder.checked},logo:image?await fileBase64(image):null});brandingInfo=result;savedLogo=Boolean(result.folders.find(r=>r.folder===folder.value)?.template?.logo);brandingDirty=false;logo.value='';remember.checked=false;saved.push('branding');}catch(error){errors.push('Branding: '+error.message);}}
  try{await refresh();const latest=state.tasks.find(row=>row.id===t.id);if(latest)t.version=latest.version;}catch(error){errors.push('Refresh: '+error.message);}
  busy=false;inputs.forEach(input=>input.disabled=false);cancel.disabled=false;close.disabled=false;markDirty();status.className='editor-status'+(errors.length?' error':'');status.textContent=(saved.length?'Saved '+saved.join(', ')+'. ':'')+(errors.length?errors.join(' · ')+' Unsaved changes are retained.':saved.length?'All changes saved.':'No changes to save.');
 }
}
function needsQuickTimeRepair(task){return task.status==='applied'&&task.published&&task.result?.streams?.some(s=>s.codec_type==='video'&&s.codec_name==='hevc'&&s.codec_tag_string==='hev1');}
function render(){renderWorkbench();}
function renderPresetSettings(){
 const container=$('preset-settings');container.replaceChildren();
 const available=(state.config.branding_presets||[]).map(p=>({...p,enabled:true}));while(available.length<5)available.push({id:'custom-'+(available.length+1),name:'Additional preset',details:'Natural colors and a simple composition.',background:'a complementary neutral tone',typography:'Clean readable title lettering.',enabled:false});
 for(const preset of available){const row=node('fieldset');row.dataset.presetId=preset.id;const enabled=node('input');enabled.type='checkbox';enabled.checked=preset.enabled;enabled.dataset.enabled='1';const enableLabel=node('label',undefined,'checkbox-label');enableLabel.append(enabled,document.createTextNode(' Include preset'));row.append(enableLabel);for(const [key,title] of [['name','Name'],['details','Prompt details (style, colors and design)'],['background','Blend / background'],['typography','Cover typography']]){const label=node('label',title),input=node(key==='details'?'textarea':'input');input.dataset.presetField=key;input.value=preset[key];label.append(input);row.append(label);}container.append(row);}
}
function readPresetSettings(){return [...$('preset-settings').children].filter(row=>row.querySelector('[data-enabled]').checked).map(row=>({id:row.dataset.presetId,...Object.fromEntries([...row.querySelectorAll('[data-preset-field]')].map(input=>[input.dataset.presetField,input.value]))}));}
function openConfig(){$('config-feedback').hidden=true;renderPresetSettings();const form=$('config-form');for(const el of form.elements){if(el.name&&el.name!=='plex_token')el.value=state.config[el.name]??el.defaultValue??'';}form.elements.plex_token.value='';$('config-dialog').showModal();}
$('settings').onclick=openConfig;
$('config-form').onsubmit=e=>{e.preventDefault();run(async()=>{const data=Object.fromEntries(new FormData(e.target));for(const key of ['max_mbps_1080','max_mbps_4k'])data[key]=Number(data[key]);data.branding_presets=readPresetSettings();await api('config',data);$('config-dialog').close();await refresh();toast('Workspace settings saved');});};
$('connect').onclick=()=>run(async()=>{if(!state.config.token_configured){openConfig();return;}await api('connect',{});await refresh();toast('Plex libraries refreshed');});
$('library-settings').onclick=()=>run(openLibrarySettings);
async function openLibrarySettings(){
 const id=libraryId,form=$('library-form');let lib=current();form.elements.profile.value=lib.profile;form.elements.themes.value=(lib.themes||[]).join(', ');
 const submit=form.querySelector('button.primary');submit.disabled=true;const note=$('mapping-status');note.textContent='Refreshing Plex folder locations…';$('mapping-rows').replaceChildren();$('library-dialog').showModal();
 try{lib=await api('library/locations',{library:id});await refresh();}catch(error){note.textContent='Using saved folder locations: '+error.message;}
 submit.disabled=false;if(!$('library-dialog').open||id!==libraryId)return;
 const saved=lib.mappings||[],detected=(lib.locations||[]).map(x=>x.path).filter(x=>typeof x==='string'&&x.startsWith('/'));
 const roots=[...new Set([...detected,...saved.map(x=>x.plex_root)])];
 const covered=root=>saved.some(m=>root===m.plex_root||root.startsWith(m.plex_root.replace(/\/$/,'')+'/'));
 if(!note.textContent.startsWith('Using saved'))note.textContent=detected.length+' Plex folders · '+detected.filter(covered).length+' mapped · '+detected.filter(r=>!covered(r)).length+' need a Mac path';
 for(const [index,root] of roots.entries()){
  const row=node('div',undefined,'mapping-row'),plexLabel=node('label','Folder '+(index+1)+' · '+(detected.includes(root)?'Plex location':'saved mapping')),plex=node('input');plex.value=root;plex.readOnly=true;plex.name='plex_root';plexLabel.append(plex);
  const localLabel=node('label','Matching folder on this Mac'),local=node('input');local.name='local_root';local.placeholder='/Volumes/Media/…';local.value=saved.find(x=>x.plex_root===root)?.local_root||'';localLabel.append(local);row.append(plexLabel,localLabel);
  if(!local.value)row.append(node('p',covered(root)?'Covered by a saved parent mapping; add a specific Mac path here only to override it.':'Not mapped yet. Files in this location need their own Mac path.','muted'));
  $('mapping-rows').append(row);
 }
 if(!roots.length)$('mapping-rows').append(node('p','Plex did not return folder locations. Refresh libraries to retrieve them.','muted'));
}
$('library-form').onsubmit=e=>{e.preventDefault();run(async()=>{const form=e.target;const mappings=[...$('mapping-rows').querySelectorAll('.mapping-row')].map(row=>({plex_root:row.querySelector('[name="plex_root"]').value,local_root:localPath(row.querySelector('[name="local_root"]').value)})).filter(x=>x.local_root);await api('library',{id:libraryId,settings:{profile:form.elements.profile.value,mappings,themes:form.elements.themes.value.split(',').map(x=>x.trim()).filter(Boolean)}});$('library-dialog').close();await refresh();toast('Library settings saved');});};
$('scan').onclick=()=>run(async()=>{await api('scan',{library:libraryId});toast('Library scan started');await refresh();});
$('run').onclick=()=>run(async()=>{await api('run',{library:libraryId});toast('Queue started');});
$('filters').onclick=e=>{const tab=e.target.closest('[data-view]');if(tab){libraryView=tab.dataset.view;filter=libraryView==='completed'?'completed':'all';selected.clear();render();}};
$('group-by').onchange=e=>{activeGrouping=e.target.value;render();};
$('queue-status').onchange=e=>{queueStatus=e.target.value;selected.clear();render();};
$('library-tools').ontoggle=()=>render();
$('select-all').onchange=e=>{for(const t of visible())e.target.checked?selected.add(t.id):selected.delete(t.id);render();};
$('queue-selected').onclick=()=>run(async()=>{let queued=0,errors=[];for(const t of visible().filter(t=>selected.has(t.id)&&canQueue(t))){const id=t.id;try{await api('task/action',{id,action:'queue',version:t.version});queued++;}catch(e){errors.push(t.title+': '+e.message);}}selected.clear();await refresh();toast(`${queued} queued`+(errors.length?' · '+errors.join('; '):''),errors.length>0);});
$('export-kometa').onclick=()=>run(async()=>{const title=prompt('Collection title');if(!title)return;const ids=[...new Set(state.tasks.filter(t=>selected.has(t.id)).map(t=>t.asset))];if(!ids.length)throw Error('Select content for the collection first');const q=new URLSearchParams({library:libraryId,title});ids.forEach(id=>q.append('asset',id));const a=node('a');a.href='/api/kometa?'+q;a.download='curator-collections.yml';a.click();toast('Collection definition exported; Kometa execution needs separate setup');});
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>{const dialog=b.closest('dialog');if(dialog)dialog.close();else closeInspector();});
$('playlist').onclick=()=>run(async()=>{if(!libraryId)throw Error('Select and scan a library first');const main=prompt('Main show title, exactly as shown in Plex',"RuPaul's Drag Race");if(!main)return;const companion=prompt('Companion show title',"RuPaul's Drag Race: Untucked!");if(!companion)return;const offset=prompt('Companion season minus main-show season (adjust for Untucked numbering)','0');if(offset===null)return;const title=prompt('Playlist title',main+' + '+companion);if(!title)return;const task=await api('playlist/preview',{library:libraryId,title,main_show:main,companion_show:companion,offset:Number(offset)});await refresh();await openTask(task.id);});
$('mcu').onclick=()=>run(async()=>{if(!libraryId)throw Error('Select a library first');const a=node('a');a.href='/api/kometa?'+new URLSearchParams({library:libraryId,mode:'mcu'});a.download='curator-mcu.yml';a.click();toast('MCU definition exported; verify movie/TV library names during Kometa setup');});
async function taskAction(t,action,settings={}){const result=await api('task/action',{id:t.id,version:t.version,action,...settings});selected.delete(t.id);await refresh();closeInspector(true);if(action==='delete'){toast('Task deleted. Media files and retained outputs are kept.');$('toast').append(button('Undo',()=>taskAction(result,'restore_task'),'subtle'));}else if(action==='remove_queue')toast('Removed from queue.');else if(action==='cancel')toast(t.status==='running'?'Cancellation requested…':'Task cancelled.');else if(action==='restore_task')toast('Task restored; it has not been requeued.');}
function taskControls(t,dialog=false){
 const controls=node('div',undefined,'task-controls');
 if(t.status==='queued')controls.append(button('Remove from queue',()=>taskAction(t,'remove_queue'),'subtle'));
 if(t.status==='running'&&['upscale','optimize','join'].includes(t.kind)){const cancel=button(t.cancel_requested?'Cancelling…':'Cancel',()=>taskAction(t,'cancel'),'subtle');cancel.disabled=Boolean(t.cancel_requested);controls.append(cancel);}
 if(!['running','publishing'].includes(t.status)&&(dialog||t.status!=='queued'))controls.append(button('Delete task',()=>taskAction(t,'delete'),'subtle'));
 return controls;
}
function jsonBlock(value){return node('pre',JSON.stringify(value,null,2));}
function recommendation(t,asset){
 const media=asset?.technical||{},box=node('section',undefined,'recommendation');
 const resolution=media.width&&media.height?`${media.width} × ${media.height}`:'unknown resolution';
 const mbps=media.bitrate?`${(media.bitrate/1000000).toFixed(1)} Mbps`:null;
 let title,description,next;
 if(['rename','join','group'].includes(t.kind)){
  title=TASK_LABELS[t.kind];description=t.evidence.note||t.reason;next=t.kind==='join'?'Approve and queue to create a separate joined output. Review every boundary before publishing.':'Approve and queue this reviewed operation, then run the library queue.';
 }else if(t.kind==='upscale'){
  title='Upscale with Topaz';description=t.evidence?.optional?`Optional Topaz processing for this ${resolution} source. The selected filter controls the output dimensions. Topaz also re-encodes the video; compare quality and file size before publishing.`:`This source is ${resolution}, below your 1080p target. Create a 1080p-or-better version while preserving its aspect ratio, then compare it with the original.`;
  next=state.config.topaz_filter?'Approve and queue the upscale, then run this library’s queue. Review the comparison before publishing.':'Configure a Topaz upscale filter in Settings, then approve and queue this task.';
 }else if(t.kind==='optimize'){
  title='Optimize the encoding with HandBrake';description=`Review this ${resolution} ${media.codec||'video'} encoding${mbps?' at '+mbps:''}. Its bitrate exceeds your review threshold; a more efficient encode may reduce its size.`;
  next=t.plan.handbrake_preset?`Task preset: ${t.plan.handbrake_preset}. Approve and queue this encode, then review the output.`:'Choose an installed preset below, then Approve & queue to save the choice and queue this task. Actual savings and quality must be checked on the output.';
 }else if(t.kind==='home'){
  const result=t.result;
  title=result?'Suggested home-movie metadata':'Analyze this home movie';
  description=result?(result.summary||'Review the suggested title and collection assignments below.'):'Use existing metadata, useful filenames, folders and sampled video frames to suggest a title, description, themed collections and cover candidates.';
  next=result?'Edit the proposed fields below, then apply them to Plex or queue the metadata changes.':'Select “Queue analysis”, then “Run queue”. Suggestions will appear here after local analysis; they have not been generated yet.';
 }else if(t.kind==='metadata'){
  const missing=[];if(!asset?.item.summary)missing.push('a description');if(!asset?.item.thumb)missing.push('cover artwork');
  title=missing.length?'Add '+missing.join(' and '):'Review Plex metadata';description=t.plan.changes?'A metadata proposal is saved. Review the proposed fields below before applying it.':'The scan identified missing metadata. Fill in a proposed correction below, or use a home-movie analysis task to generate suggestions.';
  next='Apply the displayed metadata to Plex now, queue it for later, or save a draft. Import finished artwork separately if needed.';
 }else if(t.kind==='playlist'){
  title='Create the proposed viewing order';description=`Review ${t.evidence?.ordered?.length||0} ordered items and any missing-episode warnings below.`;next='Approve and queue the playlist only when its order is correct.';
 }else{
  title=t.status==='resolved'?'This finding is resolved':'Resolve file access before processing';description=t.error||asset?.blocked||t.reason;next=t.status==='resolved'?'The latest scan no longer reports this issue.':'Check the mapped Mac folder and whether this file still exists, then rescan the library.';
 }
 box.append(node('div','RECOMMENDATION','eyebrow'),node('h3',title),node('p',description),node('p',next,'next-step'));
 return box;
}
async function openTask(id){
 if(!prepareInspector())return;inspectorMode='task';
 openedTask=id;$('task-feedback').hidden=true;$('task-reason').hidden=false;const t=state.tasks.find(t=>t.id===id),asset=state.assets.find(a=>a.id===t.asset);$('task-kind').textContent=t.kind.toUpperCase()+' · '+t.status.replaceAll('_',' ');$('task-title').textContent=t.title;$('task-reason').textContent=t.error||t.reason;selectedAssetId=t.asset;
 if(t.kind==='folder_metadata')return openFolderTask(t);
 if(asset&&['metadata','home'].includes(t.kind))return openFileEditor(t,asset);
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();
 let processingSelector=null;
 detail.append(recommendation(t,asset),progressView(t));
 if(['upscale','optimize','join'].includes(t.kind)&&t.result?.size_bytes!==undefined)detail.append(sizeComparison(t.kind==='join'?{...t,source:{size:t.evidence.total_bytes}}:t,asset));
 if(['rename','join','group'].includes(t.kind))renderFilePlan(detail,t);
 if(['upscale','optimize','join','rename'].includes(t.kind)){const log=node('details'),summary=node('summary','Publication log'),entries=node('div');log.append(summary,entries);log.ontoggle=()=>{if(log.open)run(async()=>{entries.replaceChildren(node('p','Loading publication log…','muted'));const result=await api('task/publication-log?'+new URLSearchParams({id:t.id}));entries.replaceChildren(...(result.entries.length?result.entries.map(e=>node('p',new Date(e.at).toLocaleTimeString()+' · '+e.phase+(e.detail?' · '+e.detail:'')+(e.errno?' · errno '+e.errno:''),'muted')):[node('p','No recorded publication phases yet. Older attempts have no detailed log.','muted')]));});};detail.append(log);}

 if(t.kind==='optimize'){
  if(portraitVideo(asset))detail.append(node('p','Portrait video: landscape preset resolution limits will be adapted to portrait when you approve (for example, 1080×1920 for a 1080p preset). Original proportions are preserved.','muted'));
  if(t.tool_settings?.handbrake_geometry)detail.append(node('p','Approved portrait limits: '+t.tool_settings.handbrake_geometry.max_width+'×'+t.tool_settings.handbrake_geometry.max_height,'muted'));
  const label=node('label','HandBrake preset for this task'),select=node('select');select.disabled=true;label.append(select);
  const status=node('p','Querying installed HandBrake presets…','muted'),description=node('p','','muted');
  processingSelector={ready:false,value:()=>select.value,updateQueue:()=>{}};
  let options=[];
  const updateChoice=()=>{const selected=options.find(x=>x.path===select.value);description.textContent=selected?.description||'';processingSelector.ready=Boolean(selected);processingSelector.updateQueue();};
  select.onchange=updateChoice;
  const load=async()=>{
   select.disabled=true;processingSelector.ready=false;processingSelector.updateQueue();status.textContent='Querying installed HandBrake presets…';
   try{
    const data=await api('handbrake/presets');
    if(!data.available)throw Error(data.error||'HandBrakeCLI is unavailable');
    options=data.presets;select.replaceChildren();const empty=node('option','Choose an installed preset');empty.value='';select.append(empty);
    const groups=new Map();for(const preset of options){const key=preset.group||'Custom';if(!groups.has(key)){const group=node('optgroup');group.label=key;groups.set(key,group);select.append(group);}const option=node('option',preset.name);option.value=preset.path;groups.get(key).append(option);}
    const preferred=t.plan.handbrake_preset||state.config.handbrake_preset;const selected=options.find(x=>x.path===preferred)||(options.filter(x=>x.name===preferred).length===1?options.find(x=>x.name===preferred):null);
    select.value=selected?.path||'';select.disabled=!['recommendation','failed','blocked','cancelled'].includes(t.status);
    status.textContent=`${options.length} presets found · ${data.executable}`+(data.warning?' · '+data.warning:'');updateChoice();
   }catch(error){select.replaceChildren();status.textContent=error.message==='Not found'?'Restart Curator to enable task preset discovery.':error.message;description.textContent='The HandBrake application and HandBrakeCLI are separate. Configure the CLI path in Settings if needed.';}
  };
  const controls=node('div',undefined,'cover-prompt-actions');controls.append(button('Refresh preset list',load));detail.append(label,status,description,controls);load();
 }
 if(t.kind==='playlist'){detail.append(node('h3','Proposed order'),jsonBlock(t.evidence));}
 if(t.provenance)detail.append(node('p','Evidence: '+t.provenance.join(' · '),'muted'));
 if(t.candidates){const grid=node('div',undefined,'frame-grid');for(const frame of t.candidates){const fig=node('figure'),img=node('img');img.src='/api/frames/'+t.asset+'/'+frame.file;img.alt='Candidate frame at '+frame.seconds+' seconds';fig.append(img,node('figcaption',frame.seconds+' seconds · right-click to save for Mage'));grid.append(fig);}detail.append(node('h3','Cover candidates'),grid);}

 const resumable=t.status==='blocked'&&['optimize','upscale'].includes(t.kind)&&t.output&&t.source_hash&&t.output_hash&&!t.published&&!t.validation?.length;
 if(resumable){detail.append(node('p','The processed output is retained. Resolve the reported publishing issue, then return it to review without re-encoding. Publication rechecks source/output hashes.','muted'));actions.append(button('Return output to review',async()=>{await api('task/action',{id:t.id,action:'resume_review',version:t.version});await refresh();closeInspector(true);await openTask(t.id);},'primary'));}
 if(t.kind==='rename'&&t.status==='blocked'&&t.rename_started)actions.append(button('Restore original filenames',()=>taskAction(t,'restore_rename'),'primary'));
 if(t.kind==='join'&&['blocked','awaiting_review'].includes(t.status)&&t.output&&!t.validation?.length)actions.append(button('Refresh metadata preview',async()=>{await api('task/action',{id:t.id,version:t.version,action:'refresh_join_metadata'});await refresh();closeInspector(true);await openTask(t.id);},'subtle'));
 if(t.kind==='join'&&t.status==='blocked'&&t.output&&!t.validation?.length)actions.append(button(t.published?'Resume Plex verification':'Return joined output to review',async()=>{await api('task/action',{id:t.id,version:t.version,action:'resume_join'});await refresh();closeInspector(true);await openTask(t.id);},'primary'));
 if(!(t.kind==='rename'&&t.rename_started)&&!(t.kind==='join'&&t.output)&&!resumable&&['recommendation','failed','blocked','cancelled'].includes(t.status)&&!['inspect','metadata'].includes(t.kind)){
  const approve=button(t.kind==='home'?'Queue local AI analysis':'Approve & queue',()=>taskAction(t,'queue',processingSelector?{handbrake_preset:processingSelector.value()}:{}),'primary');
  if(processingSelector){processingSelector.updateQueue=()=>{approve.disabled=!processingSelector.ready;};processingSelector.updateQueue();}actions.append(approve);
 }
 if(t.status==='awaiting_review'){
  let publishButton=null;
  if(t.kind==='join'){
   detail.append(button('Load part-boundary comparisons',async()=>{const result=await api('files/comparison',{id:t.id});t.comparison_loaded=true;if(publishButton)publishButton.disabled=false;const grid=node('div',undefined,'comparison');for(const sample of result.samples){const section=node('section');section.append(node('h3',sample.label));for(const [i,name] of sample.files.entries()){const img=node('img');img.src='/api/files/sample?'+new URLSearchParams({id:t.id,name});img.alt=sample.label+(i?' joined output':' original');section.append(node('p',i?'Joined output':'Original'),img);}grid.append(section);}detail.append(grid);}));
  }else if(['upscale','optimize'].includes(t.kind)){
   detail.append(button('Load source/output comparison',async()=>{await api('comparison',{id:t.id});t.comparison_loaded=true;if(publishButton)publishButton.disabled=false;const grid=node('div',undefined,'comparison');for(const side of ['source','output']){const column=node('div');column.append(node('h3',side==='source'?'Original':'Processed'));for(let n=0;n<4;n++){const img=node('img');img.src='/api/comparison/'+t.id+'/'+side+'/'+n+'.jpg';img.alt=side+' sample '+(n+1);column.append(img);}grid.append(column);}detail.append(grid);}));
  }
  actions.append(button('Reject result',()=>taskAction(t,'reject')));
  if(t.kind!=='home'){detail.append(node('p',t.kind==='join'?'Publication adds a new file and Plex item. All source parts stay in place.':'Publication keeps the original beside the video as filename-old.extension. Existing backups are never overwritten.','muted'));const publish=button('Accept & publish',async()=>{if(!confirm(t.kind==='join'?'I reviewed the parts and approve adding the joined file; retain every original part.':t.kind==='home'?'Apply the displayed result to Plex?':'I compared the source/output and approve replacement, retaining the original as filename-old.ext beside the video.'))return;for(const control of actions.querySelectorAll('button'))control.disabled=true;publish.textContent='Publishing…';try{await api('task/review',{id:t.id,version:t.version});await refresh();closeInspector(true);toast('Publishing started. Track copying and verification under Publishing in Processing.');}catch(error){await refresh();closeInspector(true);await openTask(t.id);throw error;}},'primary');publishButton=publish;publish.disabled=['upscale','optimize','join'].includes(t.kind)&&!t.comparison_loaded;actions.append(publish);}
 }
 if(needsQuickTimeRepair(t))actions.append(button('Fix QuickTime playback',async()=>{const result=await api('task/action',{id:t.id,version:t.version,action:'repair_quicktime'});await refresh();toast(result.quicktime_repair_warning||'QuickTime container repaired without re-encoding',Boolean(result.quicktime_repair_warning));},'primary'));
 actions.append(taskControls(t,true));
 showInspector();
}
function renderFilePlan(detail,t){
 const e=t.evidence;
 if(e.renames){const table=node('table'),head=node('tr');head.append(node('th','Current filename'),node('th','New filename'));table.append(head);for(const move of e.renames){const row=node('tr');row.append(node('td',move.before),node('td',move.after));table.append(row);}detail.append(table);}
 if(t.kind!=='rename'){const order=node('ol');for(const row of e.ordered)order.append(node('li',row.filename+' · '+row.title));detail.append(node('h3','Confirmed part order'),order);}
 if(t.kind==='join'){if(t.plan.media?.some(m=>m.streams.some(s=>s.codec_type==='data'&&s.codec_tag_string==='tmcd')))detail.append(node('p','Editing timecode tracks (tmcd) are omitted from the joined output. Video, audio, subtitles and chapters are retained; original files keep their timecode tracks.','muted'));detail.append(node('p','Output: '+e.filename),node('p',e.mode),node('p','Metadata and artwork from: '+e.metadata_title),node('p','Source parts: '+formatBytes(e.total_bytes)+' · '+(e.total_seconds/60).toFixed(1)+' minutes'));const chapters=node('ol');for(const chapter of e.chapters)chapters.append(node('li',chapter.title+' · '+chapter.start.toFixed(2)+' seconds'));detail.append(node('h3','Chapters'),chapters);}
 if(t.rename_started)detail.append(node('p',t.rename_verified?'Renamed and verified in Plex.':t.rename_restored?'Original filenames restored. Inspect Plex before making a new plan.':'Rename outcome needs inspection. Keep the retained files and recovery receipt.','muted'));
 if(t.kind==='join'&&t.plan.metadata_snapshot){const metadata=t.plan.metadata_snapshot.metadata,box=node('details');box.append(node('summary','Metadata to copy'));for(const [name,label] of [['title','Source title'],['summary','Description'],['studio','Studio'],['tagline','Tagline'],['genre','Genres'],['label','Labels'],['collection','Collections']])box.append(node('p',label+': '+(Array.isArray(metadata[name])?metadata[name].join(', '):metadata[name]||'—')));box.append(node('p','Cast: '+(metadata.cast.map(c=>c.name+(c.role?' ('+c.role+')':'')).join(', ')||'—')));detail.append(box);if(t.metadata_refreshed)detail.append(node('p','Metadata preview refreshed. The joined video and comparison are retained. Review the details before publishing.','muted'));}
 if(t.error)detail.append(node('p',t.error,'error'));
}
async function openFileOperation(asset,kind){
 if(!prepareInspector())return;inspectorMode='file-tools';openedTask='file-tools:'+asset.id+':'+kind;const operationToken=openedTask;
 const detail=$('task-detail'),actions=$('task-buttons');
 $('task-title').textContent=TASK_LABELS[kind];$('task-kind').textContent='FILE TOOLS';$('task-reason').textContent=kind==='rename'?'Preview filenames before changing files or Plex.':'Confirm the exact parts and their order.';$('task-feedback').hidden=true;
 detail.replaceChildren();actions.replaceChildren();
 const field=(label,value)=>{const wrap=node('label',label),input=node('input');input.value=value;wrap.append(input);detail.append(wrap);return input;};
 const currentName=(asset.plex_path||asset.local_path).split('/').pop();
 const title=kind==='rename'?null:field(kind==='join'?'Joined Plex title':'Collection / playlist title',asset.title);
 const filename=kind==='group'?null:field('Filename including extension',kind==='rename'?currentName:'Joined.mkv');
 let ordered=[asset.id],chapterNames=new Map(),metadataAsset=asset.id,mode=null,groupMode=null;
 const partsBox=node('div'),all=state.assets.filter(a=>a.library===asset.library&&a.present!==false);
 if(kind!=='rename'){
  const suggested=await api('files/suggestions?'+new URLSearchParams({asset:asset.id}));if(openedTask!==operationToken)return;ordered=suggested.assets;title.value=suggested.title;
  for(const warning of suggested.warnings)detail.append(node('p',warning,'muted'));
  const choices=node('label','Add a file'),select=node('select');select.setAttribute('aria-label','Add part');choices.append(select);detail.append(choices,partsBox);
  const metadata=node('label','Use metadata and artwork from'),metadataSelect=node('select');metadataSelect.setAttribute('aria-label','Metadata source');metadata.append(metadataSelect);if(kind==='join')detail.append(metadata);
  function renderParts(){
   select.replaceChildren(node('option','Choose a file to add…'));select.firstChild.value='';for(const row of all.filter(a=>!ordered.includes(a.id))){const option=node('option',(row.plex_path||row.local_path).split('/').pop());option.value=row.id;select.append(option);}
   partsBox.replaceChildren();metadataSelect.replaceChildren();for(const [i,id] of ordered.entries()){const row=all.find(a=>a.id===id),section=node('div',undefined,'part-row');section.append(node('strong',(i+1)+'. '+(row.plex_path||row.local_path).split('/').pop()));
    const controls=node('div',undefined,'actions'),up=button('Move up',()=>{[ordered[i-1],ordered[i]]=[ordered[i],ordered[i-1]];renderParts();}),down=button('Move down',()=>{[ordered[i+1],ordered[i]]=[ordered[i],ordered[i+1]];renderParts();});up.disabled=i===0;down.disabled=i===ordered.length-1;controls.append(up,down,button('Remove',()=>{ordered=ordered.filter(x=>x!==id);renderParts();}));section.append(controls);
    if(kind==='join'){const label=node('label','Chapter title'),input=node('input');input.value=chapterNames.get(id)||'Part '+(i+1);input.oninput=()=>chapterNames.set(id,input.value);label.append(input);section.append(label);}
    partsBox.append(section);const option=node('option',row.title);option.value=id;metadataSelect.append(option);
   }if(!ordered.includes(metadataAsset))metadataAsset=ordered[0];metadataSelect.value=metadataAsset||'';
  }
  select.onchange=()=>{if(select.value){ordered.push(select.value);renderParts();}};metadataSelect.onchange=()=>metadataAsset=metadataSelect.value;renderParts();
 }
 if(kind==='join'){
  const label=node('label','Processing'),select=node('select');select.setAttribute('aria-label','Join processing');for(const [value,text] of [['copy','Join without re-encoding (matching streams)'],['normalize','Normalize differing parts (re-encode)']]){const option=node('option',text);option.value=value;select.append(option);}label.append(select);detail.append(label,node('p','Normalization uses the first part’s orientation and canvas, H.264 8-bit SDR at 30 fps and AAC stereo. Other proportions are letterboxed. Original parts are always retained.','muted'));mode=select;
 }else if(kind==='group'){
  const label=node('label','Create / update'),select=node('select');for(const [value,text] of [['both','Collection and ordered playlist'],['playlist','Ordered playlist'],['collection','Collection']]){const option=node('option',text);option.value=value;select.append(option);}label.append(select);detail.append(label);groupMode=select;
 }
 const preview=button('Preview '+(kind==='rename'?'rename':kind==='join'?'joined video':'grouping'),async()=>{
  preview.disabled=true;
  try{const task=await api('files/plan',{kind,assets:ordered,title:title?.value||asset.title,filename:filename?.value,mode:mode?.value,group_mode:groupMode?.value,metadata_asset:metadataAsset,chapter_titles:ordered.map((id,i)=>chapterNames.get(id)||'Part '+(i+1))});await refresh();closeInspector(true);await openTask(task.id);}finally{preview.disabled=false;}
 },'primary');actions.append(button('Cancel',()=>closeInspector()),preview);showInspector();
}
let presencePending=false;
async function syncCatalog(){if(!libraryId||presencePending||!state.config.token_configured)return;presencePending=true;try{await api('library/presence',{library:libraryId});}catch(error){if(error.message!=='Not found')throw error;}finally{presencePending=false;}}
initWorkbench();run(async()=>{await refresh();await syncCatalog();});setInterval(()=>run(refresh),4000);setInterval(()=>run(syncCatalog),60000);

function folderValue(value){if(Array.isArray(value))return value.map(v=>typeof v==='string'?v:v.name+(v.role?' ('+v.role+')':'')+(v.photo||v.thumb?' · photo':'')).join(', ')||'(empty)';return value||'(empty)';}
function folderDiff(row){
 const section=node('section',undefined,'folder-diff');section.append(node('h3',row.filename));
 if(row.error){section.append(node('p','Skipped: '+row.error,'error'));return section;}
 const entries=Object.entries(row.changes||{});if(!entries.length&&!Object.keys(row.artwork||{}).length){section.append(node('p','No changes needed','muted'));return section;}
 const table=node('table'),head=node('tr');for(const title of ['Field','Current','Proposed'])head.append(node('th',title));table.append(head);
 for(const [field,value] of entries){const tr=node('tr');tr.append(node('th',({summary:'Description',genre:'Tags',label:'Labels',collection:'Collections'})[field]||field),node('td',folderValue(row.before?.[field])),node('td',folderValue(value)));table.append(tr);}
 section.append(table);
 for(const [kind,value] of Object.entries(row.artwork||{})){const art=node('div',undefined,'folder-art-preview'),image=node('img');image.src='/api/folders/image?'+new URLSearchParams({photo:value.photo});image.alt='Proposed '+ARTWORK_LABELS[kind];art.append(node('p',ARTWORK_LABELS[kind]+(row.art_before?.[kind]?' · replaces existing art':' · adds missing art')),image);section.append(art);}
 return section;
}
async function openFolder(fid){
 if(!prepareInspector())return;inspectorMode='folder';
 openedTask='folder:'+fid;$('task-kind').textContent='FOLDER METADATA';$('task-title').textContent='Loading folder…';$('task-reason').hidden=true;$('task-feedback').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();showInspector();
 const info=await api('folders/read?'+new URLSearchParams({id:fid}));if(openedTask!=='folder:'+fid||!inspectorOpen())return;
 $('task-title').textContent=info.folder.name;if(info.folder.mapped===false){detail.append(node('p','This Plex folder needs a matching Mac path in Library settings.'));actions.append(button('Library settings',()=>{closeInspector(true);return openLibrarySettings();}));return;}detail.append(node('p',info.folder.path,'folder-path'),node('p','Preview changes for each Plex title, then approve and queue. Titles with multiple files are updated once. Saving defaults changes no Plex metadata.','muted'));
 const initial=info.defaults||info.inherited?.[0]||{fields:{},artwork:{},mode:'fill',recursive:false};
 if(!info.defaults&&info.inherited?.length)detail.append(node('p','Starting from parent defaults: '+info.inherited[0].folder,'muted'));
 let preview=null,busy=false,castUI=null,approve=null;const result=node('div');
 const status=node('p','','editor-status');status.setAttribute('role','status');
 const scope=node('label',undefined,'checkbox-label'),recursive=node('input');recursive.type='checkbox';recursive.checked=initial.recursive;scope.append(recursive,document.createTextNode(' Include subfolders ('+info.folder.count+' scanned files total; '+info.folder.direct_count+' directly in this folder)'));detail.append(scope);
 const modeLabel=node('label','Apply mode'),mode=node('select');for(const [value,text] of [['fill','Fill missing fields'],['merge','Merge lists and fill missing fields'],['replace','Replace selected fields']]){const option=node('option',text);option.value=value;mode.append(option);}mode.value=initial.mode;modeLabel.append(mode);detail.append(modeLabel,node('p','Merge keeps existing cast, tags and labels and adds missing entries. Existing scalar fields and artwork are kept. Replace can clear an enabled field if its value is empty.','muted'));
 const fields={},enabled={},grid=node('div',undefined,'metadata-grid');
 for(const [field,label] of [['studio','Studio / creator'],['genre','Tags / genres'],['label','Labels'],['collection','Collections'],['tagline','Tagline'],['title','Title (optional; same title for every file)'],['summary','Description (optional; shared text)']]){
  const box=node('div'),checkLabel=node('label',undefined,'checkbox-label'),check=node('input');check.type='checkbox';check.checked=Object.hasOwn(initial.fields,field);enabled[field]=check;checkLabel.append(check,document.createTextNode(' '+label));
  const input=node(field==='summary'?'textarea':'input');input.setAttribute('aria-label',label);input.value=Array.isArray(initial.fields[field])?initial.fields[field].join(', '):initial.fields[field]||'';input.disabled=!check.checked;fields[field]=input;check.onchange=()=>{input.disabled=!check.checked;input.collectionPicker?.setDisabled(!check.checked);invalidate();};input.oninput=invalidate;box.append(checkLabel,input);if(['genre','label','collection'].includes(field))box.append(collectionPicker(input,info.folder.library,initial.fields[field]||[],invalidate,!check.checked,field));grid.append(box);
 }
 detail.append(grid);
 const castToggle=node('label',undefined,'checkbox-label'),useCast=node('input');useCast.type='checkbox';useCast.checked=Object.hasOwn(initial.fields,'cast');castToggle.append(useCast,document.createTextNode(' Apply shared cast'));detail.append(castToggle);
 castUI=await castEditor({}, {},invalidate,{folder:true,rows:initial.fields.cast||[]});if(openedTask!=='folder:'+fid||!inspectorOpen())return;castUI.section.hidden=!useCast.checked;useCast.onchange=()=>{castUI.section.hidden=!useCast.checked;invalidate();};detail.append(castUI.section);
 const artwork=node('section');artwork.append(node('h3','Shared artwork'),node('p','Per-video cover art stays in the file editor. Select shared backgrounds, logos and square art here.','muted'));const images={};
 for(const kind of ['background','logo','square']){
  const label=node('label',ARTWORK_LABELS[kind]),input=node('input');input.type='file';input.accept='image/png,image/jpeg';label.append(input);const use=node('input');use.type='checkbox';use.checked=Boolean(initial.artwork?.[kind]);const useLabel=node('label',undefined,'checkbox-label');useLabel.append(use,document.createTextNode(' Apply '+ARTWORK_LABELS[kind].toLowerCase()));const image=node('img');image.className='editor-image';image.alt='Shared '+ARTWORK_LABELS[kind];image.hidden=!use.checked;if(use.checked)image.src='/api/folders/image?'+new URLSearchParams({photo:initial.artwork[kind].photo});
  images[kind]={input,use,photo:initial.artwork?.[kind]?.photo};use.onchange=invalidate;input.onchange=()=>{const file=input.files[0];if(file){if(file.size>10*1024*1024){input.value='';throwError('Choose artwork under 10 MiB');return;}use.checked=true;image.hidden=false;const url=URL.createObjectURL(file);image.src=url;image.onload=()=>URL.revokeObjectURL(url);}invalidate();};artwork.append(useLabel,label,image);
 }
 detail.append(artwork);
 const brandSection=node('details');brandSection.append(node('summary','Creator branding for Mage prompts'));const brandToggle=node('input');brandToggle.type='checkbox';brandToggle.checked=Boolean(info.branding||initial.branding);const brandLabel=node('label',undefined,'checkbox-label');brandLabel.append(brandToggle,document.createTextNode(' Save creator branding with folder defaults'));const creator=node('input');creator.setAttribute('aria-label','Branding creator');creator.value=(info.branding||initial.branding)?.creator||'';const preset=node('select');preset.setAttribute('aria-label','Branding preset');for(const p of state.config.branding_presets||[]){const o=node('option',p.name);o.value=p.id;preset.append(o);}preset.value=(info.branding||initial.branding)?.preset_id||state.config.branding_presets?.[0]?.id||'';brandSection.append(brandLabel,creator,preset,node('p','Used by the existing per-file Mage prompt and confirmation. Existing folder logo references are retained.','muted'));if(current()?.profile==='home')detail.append(brandSection);
 detail.append(result);
 const close=button('Cancel',()=>closeInspector(true)),save=button('Save folder defaults',()=>work(async()=>{const data=await payload();const saved=await api('folders/defaults',{id:fid,settings:data,revision:info.defaults?.revision??null,branding_revision:info.branding_revision});info.defaults=saved.defaults;info.branding_revision=saved.branding_revision;status.textContent='Folder defaults saved. Future scans will suggest them for matching files.';})),previewButton=button('Preview changes',()=>work(async()=>{status.textContent='Reading current Plex metadata and building preview…';const next=await api('folders/preview',{id:fid,settings:await payload()});preview=next;result.replaceChildren();const count=next.rows.filter(r=>!r.error&&(Object.keys(r.changes).length||Object.keys(r.artwork).length)).length,skipped=next.rows.filter(r=>r.error).length;result.append(node('h3','Preview: '+count+' titles will change'+(skipped?' · '+skipped+' skipped':'')),...next.rows.map(folderDiff));approve.hidden=!count;previewButton.hidden=Boolean(count);approve.disabled=!count;status.textContent=count?'Review the proposed values below. Nothing has been sent to Plex.':skipped?'No changes queued. Check the skipped files below.':'Everything already matches. No tasks queued or sent for review.';}),'primary');approve=button('Approve & queue',()=>work(async()=>{if(!preview)return;const queued=await api('folders/queue',{preview:preview.id});await refresh();closeInspector(true);toast(queued.queued+' folder metadata tasks queued. Run the library queue to apply.');}),'primary');approve.hidden=true;
 actions.append(status,close,save,previewButton,approve);
 function invalidate(){inspectorDirty=true;preview=null;if(approve){approve.hidden=true;previewButton.hidden=false;}result.replaceChildren();status.textContent='Preview required for these settings.';}
 function throwError(message){status.textContent=message;toast(message,true);}
 async function work(fn){if(busy)return;busy=true;for(const b of actions.querySelectorAll('button'))b.disabled=true;const inputs=[...detail.querySelectorAll('input,select,textarea,button,fieldset')],disabled=inputs.map(x=>x.disabled);inputs.forEach(x=>x.disabled=true);$('task-dialog').querySelector('[data-close]').disabled=true;try{await fn();}finally{busy=false;inputs.forEach((x,i)=>x.disabled=disabled[i]);for(const b of actions.querySelectorAll('button'))b.disabled=false;$('task-dialog').querySelector('[data-close]').disabled=false;if(preview)approve.disabled=!preview.rows.some(r=>!r.error&&(Object.keys(r.changes).length||Object.keys(r.artwork).length));}}
 async function payload(){const values={};for(const [field,input] of Object.entries(fields)){if(enabled[field].checked)values[field]=['genre','label','collection'].includes(field)?metadataListValue(input):input.value;}if(useCast.checked)values.cast=await castUI.payload();const art={};for(const [kind,row] of Object.entries(images)){if(!row.use.checked)continue;if(row.input.files[0])art[kind]={image:await fileBase64(row.input.files[0])};else if(row.photo)art[kind]={photo:row.photo};else throw Error('Choose '+ARTWORK_LABELS[kind]+' to apply');}return {fields:values,artwork:art,mode:mode.value,recursive:recursive.checked,branding:current()?.profile==='home'&&brandToggle.checked?{version:2,creator:creator.value,preset_id:preset.value}:null};}
 recursive.onchange=mode.onchange=brandToggle.onchange=preset.onchange=invalidate;creator.oninput=invalidate;
}
async function openFolderTask(t){
 if(['recommendation','blocked','failed','cancelled'].includes(t.status))return openFolder(t.plan.folder);
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren();actions.replaceChildren();detail.append(folderDiff({filename:t.title,before:t.metadata_before,changes:t.plan.changes,artwork:t.plan.artwork,art_before:t.plan.art_before}));
 detail.append(node('p',t.error||t.status.replaceAll('_',' '),'muted'));actions.append(taskControls(t,true));showInspector();
}
