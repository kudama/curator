'use strict';
// Rename recovery (#154): read a rename receipt, then explicitly restore retained artwork or cast pictures.
// Opening a receipt never writes. Artwork restores become ordinary artwork reviews; picture restores use the cast save.
let renameReceiptEpoch=0;
const RENAME_STATUS={captured:'Waiting for the rename to finish',moved:'Waiting for Plex to scan the renamed file',review:'Something changed after the rename',reconciled:'Checked: Plex kept everything',blocked:'Needs a manual check',void:'Rename was rolled back; nothing to restore'};
const RENAME_ART_STATE={retained:'Plex still has it',changed:'Plex now shows a different image',missing:'Plex has no image now',unreadable:'Plex image could not be read',pending:'Not checked yet'};
const RENAME_PERSON_STATE={retained:'Plex still has it',changed:'Plex shows a different picture',missing:'No picture now',person_missing:'No longer credited',unreadable:'Plex picture could not be read',pending:'Not checked yet'};
const RENAME_KEPT={reference:'Picture from the Plex agent; Plex can fetch it again',none:'No picture before the rename',unavailable:'Picture could not be kept'};
const RENAME_FIELD={title:'Title',summary:'Description',studio:'Studio',tagline:'Tagline',genre:'Categories',collection:'Collections',label:'Labels',cast:'Cast'};
const RENAME_ART_KIND={cover:'Poster',background:'Background',logo:'Logo',square:'Square art'};
function renameRestoreText(restore){
 if(!restore)return '';
 return ({waiting_for_review:'Restore is waiting for your review',queued:'Restore is queued',publishing:'Restoring…',restored:'Restored and verified',rejected:'You rejected the restore',removed:'The restore was removed',needs_attention:'Restore needs attention'+(restore.error?': '+restore.error:''),failed:'Restore failed'+(restore.error?': '+restore.error:'')})[restore.state]||restore.state;
}
function renameValue(field,value){
 if(value===null||value===undefined)return 'Unknown';
 if(field==='cast')return value.length?value.map(r=>r.name+(r.role?' ('+r.role+')':'')).join(', '):'None';
 if(Array.isArray(value))return value.length?value.join(', '):'None';
 return value===''?'Empty':String(value);
}
function renameImage(src,alt){const img=node('img');img.src=src;img.alt=alt;img.loading='lazy';img.className='rename-image';img.onerror=()=>{const empty=node('p','No image','muted');img.replaceWith(empty);};return img;}
async function openRenameReceipt(id){
 if(!prepareInspector())return;
 const epoch=++renameReceiptEpoch,key='rename-receipt:'+id;openedTask=key;inspectorMode='rename-receipt';
 $('task-kind').textContent='RENAME RECOVERY';$('task-title').textContent='Loading receipt…';$('task-reason').hidden=true;
 const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren(node('p','Loading…','muted'));actions.replaceChildren();showInspector();
 const current=()=>inspectorMode==='rename-receipt'&&openedTask===key&&epoch===renameReceiptEpoch;
 let busy=false;
 async function load(message){
  let view;
  try{view=await api('rename/receipt?'+new URLSearchParams({id}));}
  catch(error){if(current()){$('task-title').textContent='Rename recovery';detail.replaceChildren(node('p',error.message,'error'));}return;}
  if(current())render(view,message);
 }
 async function act(run,done){
  if(busy)return;busy=true;let message;
  for(const control of detail.querySelectorAll('button,input'))control.disabled=true;
  try{message=await run();}catch(error){message={error:error.message};}
  finally{busy=false;if(current())await load(message);}
  if(done&&message&&!message.error)done(message);
 }
 function render(view,message){
  $('task-title').textContent=view.title;detail.replaceChildren();actions.replaceChildren();
  const status=node('p',RENAME_STATUS[view.status]||view.status,'rename-status');status.setAttribute('role','status');detail.append(status);
  if(message?.error)detail.append(node('p',message.error,'error'));else if(message?.text)detail.append(node('p',message.text,'next-step'));
  detail.append(node('p','Renamed from '+view.renamed.before+' to '+view.renamed.after+(view.rematched?' · Plex matched it again as a new item':'')+(view.rolled_back?' · the rename was rolled back':''),'muted'));
  if(view.reason)detail.append(node('p',view.reason,'task-error'));
  if(['captured','moved'].includes(view.status))detail.append(node('p','Curator compares the item after Plex scans the renamed file. It does not force a Plex refresh.','muted'));
  detail.append(node('p','“Now” is what Curator saw at the last library scan. Opening this receipt changes nothing.','muted'));
  // Metadata: compare, then hand off to the existing metadata review.
  const changed=view.metadata.filter(m=>m.state==='differs'||m.state==='superseded'),kept=view.metadata.filter(m=>m.state==='retained');
  const meta=node('section',undefined,'rename-section');meta.append(node('h3','Metadata'));
  if(!changed.length)meta.append(node('p',view.metadata.some(m=>m.state==='pending')?'Not checked yet.':'Plex kept every field.','muted'));
  for(const m of changed){const row=node('div',undefined,'rename-field');row.append(node('strong',RENAME_FIELD[m.field]||m.field),node('p','Before the rename: '+renameValue(m.field,m.captured)),node('p','Now: '+renameValue(m.field,m.current),'muted'),node('p',m.state==='superseded'?'You changed this in Curator later; your newer value is kept.':'Plex lost this after the rename.',m.state==='superseded'?'muted':'rename-lost'));meta.append(row);}
  if(kept.length){const box=node('details');box.append(node('summary',kept.length+' fields kept by Plex'),node('p',kept.map(m=>RENAME_FIELD[m.field]||m.field).join(', '),'muted'));meta.append(box);}
  const restore=view.metadata_restore;
  if(restore?.state==='proposed'&&restore.task)meta.append(node('p','A restore of '+(restore.fields||[]).map(f=>RENAME_FIELD[f]||f).join(', ')+' is ready in the metadata editor. Nothing is written until you save it there.','muted'),button('Review metadata restore',()=>openTask(restore.task,'metadata'),'subtle'));
  else if(restore?.state==='conflict')meta.append(node('p','Restore not proposed: '+restore.reason,'task-error'));
  else if(restore?.state==='not_proposed')meta.append(node('p','Restore not proposed: '+restore.reason,'muted'));
  detail.append(meta);
  // Artwork: retained original beside what Plex shows now; restores become artwork reviews.
  if(view.artwork.length){
   const art=node('section',undefined,'rename-section'),grid=node('div',undefined,'rename-grid'),chosen=new Set();art.append(node('h3','Artwork'));
   for(const a of view.artwork){
    const card=node('article',undefined,'rename-card'),pair=node('div',undefined,'rename-pair'),label=RENAME_ART_KIND[a.kind]||a.kind;
    const kept=node('figure');kept.append(a.verified?renameImage('/api/rename/receipt/image?'+new URLSearchParams({id:view.id,kind:a.kind}),label+' kept before the rename'):node('p',a.problem||'Not available','error'),node('figcaption','Kept before the rename'));
    const now=node('figure');now.append(renameImage('/api/artwork/target-image?'+new URLSearchParams({asset:view.asset,kind:a.kind}),label+' in Plex now'),node('figcaption','In Plex now'));
    pair.append(kept,now);card.append(node('strong',label),pair,node('p',RENAME_ART_STATE[a.state]||a.state,a.state==='retained'?'muted':'rename-lost'));
    if(a.restore)card.append(node('p',renameRestoreText(a.restore),a.restore.state==='needs_attention'?'task-error':'muted'));
    if(a.restore?.task&&['waiting_for_review','needs_attention'].includes(a.restore.state))card.append(button('Open restore review',()=>openTask(a.restore.task,'artwork'),'subtle'));
    if(a.can_restore){const box=node('label',undefined,'rename-choice'),check=node('input');check.type='checkbox';check.onchange=()=>{check.checked?chosen.add(a.kind):chosen.delete(a.kind);go.disabled=!chosen.size;};box.append(check,document.createTextNode(' Restore this '+label.toLowerCase()));card.append(box);}
    grid.append(card);
   }
   const go=button('Create restore review',()=>act(async()=>{const result=await api('rename/receipt/restore-artwork',{id:view.id,version:view.version,kinds:[...chosen]});return {text:(result.tasks.length?result.tasks.length+' restore '+(result.tasks.length===1?'review is':'reviews are')+' waiting in Artwork. Nothing is published until you approve.':'')+(result.already.length?' Plex already shows the kept image for '+result.already.map(k=>RENAME_ART_KIND[k]||k).join(', ')+'.':'')};}),'primary');
   go.disabled=true;art.append(grid);if(view.artwork.some(a=>a.can_restore))art.append(go);detail.append(art);
  }
  // Cast pictures: only pictures kept from Plex itself can be restored; everyone else stays as they are.
  if(view.portraits.length){
   const people=node('section',undefined,'rename-section'),grid=node('div',undefined,'rename-grid'),chosen=new Map();people.append(node('h3','Cast pictures'));
   for(const p of view.portraits){
    const card=node('article',undefined,'rename-card person');card.append(node('strong',p.name+(p.role?' · '+p.role:'')));
    if(p.retained==='retained'){
     card.append(p.verified?renameImage('/api/rename/receipt/image?'+new URLSearchParams({id:view.id,person:p.index}),'Picture of '+p.name+' kept before the rename'):node('p',p.problem,'error'),node('p',RENAME_PERSON_STATE[p.state]||p.state,p.state==='retained'?'muted':'rename-lost'));
     if(p.restore)card.append(node('p',renameRestoreText(p.restore),p.restore.state==='failed'?'task-error':'muted'));
     if(p.can_restore){const box=node('label',undefined,'rename-choice'),check=node('input');check.type='checkbox';check.onchange=()=>{check.checked?chosen.set(p.index,p.name):chosen.delete(p.index);go.disabled=!chosen.size;};box.append(check,document.createTextNode(' Restore this picture'));card.append(box);}
    }else card.append(node('p',p.problem||RENAME_KEPT[p.retained]||p.retained,'muted'));
    grid.append(card);
   }
   const go=button('Restore selected pictures',()=>{const names=[...chosen.values()];if(!confirm('Put back the kept '+(names.length===1?'picture':'pictures')+' for '+names.join(', ')+'? Everyone else’s credits and pictures stay as they are.'))return;act(async()=>{await api('rename/receipt/restore-portraits',{id:view.id,version:view.version,people:[...chosen.keys()],cast_digest:view.cast_digest});return {text:'Pictures restored and checked in Plex.'};});},'primary');
   go.disabled=true;people.append(grid);if(view.portraits.some(p=>p.can_restore))people.append(go);detail.append(people);
  }
  actions.append(button('Close',()=>closeInspector(),'subtle'));
 }
 await load();
}
