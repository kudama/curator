'use strict';
let mageDiscovery=null,mageDiscoveryPromise=null;
function mageModelLabel(id){return {'mango-v2':'Mango 2','mango-v3':'Mango 3','mango-v4':'Mango 4','mango-v3s':'Mango 3S','mango-v3-turbo':'Mango 3 Turbo'}[id]||id;}
function fillMageModels(select,preferred,catalog=mageDiscovery){
 select.replaceChildren();const rows=catalog?.model_catalog||[];
 for(const group of ['Mango','Other image models']){const items=rows.filter(r=>r.group===group);if(!items.length)continue;const section=node('optgroup');section.label=group;for(const row of items){const option=node('option',row.name+(row.supported?'':' · unavailable'));option.value=row.id;option.disabled=!row.supported;section.append(option);}select.append(section);}
 if(preferred&&!rows.some(r=>r.id===preferred)){const option=node('option',mageModelLabel(preferred)+(catalog?' · unavailable':' · saved preference'));option.value=preferred;option.disabled=Boolean(catalog);select.append(option);}
 if(!rows.length&&!preferred){const option=node('option','Connect Mage and refresh models');option.value='';select.append(option);}
 select.value=preferred||'';
}
async function discoverMage(){
 if(mageDiscoveryPromise)return mageDiscoveryPromise;
 mageDiscoveryPromise=api('mage/check',{}).then(result=>{mageDiscovery=result;return result;}).finally(()=>{mageDiscoveryPromise=null;});return mageDiscoveryPromise;
}
function syncMageResolution(model,resolution,preferred){
 const row=mageDiscovery?.model_catalog?.find(r=>r.id===model.value);if(!row)return;
 const previous=preferred??resolution.value;resolution.replaceChildren();for(const value of row.resolutions){const option=node('option',value);option.value=value;resolution.append(option);}
 if(!row.resolutions.length){const option=node('option','Model dimensions');option.value='';resolution.append(option);}
 resolution.value=row.resolutions.includes(previous)?previous:row.resolutions[0]||'';
}
function prepareMageSettings(){
 const select=$('mage-default-model');fillMageModels(select,state.config.mage_default_model||'mango-v3');
 $('manager-mage-key').value='';$('manager-mage-status').textContent=state.config.mage_configured?'API key saved on the Curator host.':'Mage is not connected.';
 $('mage-account-status').textContent=mageDiscovery?'Balance '+(mageDiscovery.balance_status==='available'?mageDiscovery.balance+' Gems':'unavailable'):'Test the connection to load available models and account balance.';
 $('mage-default-resolution').value=state.config.mage_default_resolution||'2K';syncMageResolution(select,$('mage-default-resolution'),state.config.mage_default_resolution||'2K');
}
function setupMageSettings(){
 $('manager-mage-save').onclick=()=>run(async()=>{const key=$('manager-mage-key').value;if(!key)throw Error('Enter a key, or use Remove connection.');await api('mage/key',{key});$('manager-mage-key').value='';mageDiscovery=null;await refresh();prepareMageSettings();});
 $('manager-mage-remove').onclick=()=>run(async()=>{await api('mage/key',{key:''});mageDiscovery=null;await refresh();prepareMageSettings();});
 $('manager-mage-check').onclick=async()=>{const control=$('manager-mage-check'),status=$('mage-account-status');control.disabled=true;status.textContent='Checking Mage connection and available models…';try{const result=await discoverMage(),preferred=$('mage-default-model').value;fillMageModels($('mage-default-model'),preferred,result);syncMageResolution($('mage-default-model'),$('mage-default-resolution'));status.textContent=result.model_catalog.length+' image models · Balance '+(result.balance_status==='available'?result.balance+' Gems':'unavailable')+' · Monthly committed '+result.budget.committed+' Gems';}catch(error){status.textContent=error.message;}finally{control.disabled=false;}};
 $('mage-default-model').onchange=()=>syncMageResolution($('mage-default-model'),$('mage-default-resolution'));
}
async function renderSavedMageConsent(tasks,detail,actions){
 const note=node('p','Check the current total before approving these saved plans.','muted editor-status'),generate=button('Generate',async()=>{if(!quote)return;const owners=tasks.map(t=>catalogIndex().byId.get(t.asset)),decision=await confirmGenerationMetadata(owners);if(decision==='edit'){quote=null;generate.disabled=true;await editGenerationMetadata(owners);return;}if(decision!=='generate')return;generate.disabled=true;try{await generateMageQuote(quote.id,detail,actions);quote=null;}catch(error){note.textContent=error.message;}},'primary generate-action');let quote=null;generate.disabled=true;
 const check=button('Check cost',async()=>{check.disabled=true;quote=null;generate.disabled=true;try{const priced=await api('mage/quote',{tasks:tasks.map(t=>({id:t.id,version:t.version}))}),account=await discoverMage();const remaining=account.budget.limit?account.budget.limit-account.budget.committed:Infinity;note.textContent=priced.count+' '+(priced.count===1?'option':'options')+' · '+priced.total+' Gems estimated · Balance '+(account.balance_status==='available'?account.balance:'unavailable');generate.textContent='Generate';if(account.balance_status==='available'&&account.balance>=priced.total&&remaining>=priced.total){quote=priced;generate.disabled=false;}else note.textContent+=' · Check balance and budget before generation';}catch(error){note.textContent=error.message;}finally{check.disabled=false;}},'text-button');actions.append(note,check,generate);
}

async function generateMageQuote(quoteId,detail,actions){
 const owner=openedTask,result=await api('mage/authorize',{quote:quoteId,consent:true});
 if(openedTask===owner){inspectorDirty=false;inspectorBack=null;detail.replaceChildren(node('p',result.queued+' generation jobs approved. Starting the artwork queue…','muted'));actions.replaceChildren(button('View generation queue',showMageGenerationQueue,'subtle'));}
 let failure=null;
 try{await api('run',{scope:'all',kind:'mage_generation'});}catch(error){failure=error;}
 try{await refresh();}catch(error){failure=failure||error;}
 if(failure&&result.task_ids?.length&&result.task_ids.every(id=>state.tasks.some(t=>t.id===id&&['running','awaiting_review','applied'].includes(t.status))))failure=null;
 if(openedTask===owner)showMageGenerationQueue();
 if(failure)toast('Generation approval saved. Open Artwork generation in Queue to inspect or resume: '+failure.message,true);
 return result;
}
function showMageGenerationQueue(){
 inspectorDirty=false;inspectorBack=null;closeInspector(true);queueLibrary='all';queueStatus='all';searchText='';$('file-search').value='';setScreen('processing');
}

function generationMetadataIssues(asset){
 if(!asset||asset.artwork_target)return [];
 const title=asset.title||asset.item?.title||'',issues=[];
 if(!title.trim())issues.push('Title is missing.');
 if(/\bs\d{1,4}e\d{1,4}\b|\.(mp4|mkv|mov|avi|m4v)$/i.test(title))issues.push('The title contains an episode code or filename extension that could appear in the artwork.');
 if(!asset.item?.summary?.trim())issues.push('Description is missing, so Mage has little context.');
 return issues;
}
function confirmGenerationMetadata(assets){
 const rows=(Array.isArray(assets)?assets:[assets]).filter(asset=>generationMetadataIssues(asset).length);
 if(!rows.length)return Promise.resolve('generate');
 return new Promise(resolve=>{
  const dialog=node('dialog',undefined,'metadata-generation-warning'),title=node('h2','Review metadata before spending Gems');title.id='metadata-generation-warning-title';dialog.setAttribute('aria-labelledby',title.id);dialog.append(title,node('p','Mage uses the title and description below. Review missing fields and filename-like titles before generating.','muted'));
  for(const asset of rows){const section=node('section');section.append(node('h3',asset.title||'Untitled'),node('p',asset.item?.summary||'No description','muted'));for(const issue of generationMetadataIssues(asset))section.append(node('p',issue,'muted'));dialog.append(section);}
  const actions=node('div',undefined,'dialog-actions');const finish=value=>{dialog.close();dialog.remove();resolve(value);};const edit=button('Edit metadata',()=>finish('edit'),'subtle');actions.append(button('Cancel',()=>finish('cancel'),'subtle'),edit,button('Generate anyway',()=>finish('generate'),'primary'));dialog.append(actions);dialog.addEventListener('cancel',event=>{event.preventDefault();finish('cancel');});document.body.append(dialog);dialog.showModal();edit.focus();
 });
}
async function editGenerationMetadata(assets){
 const rows=(Array.isArray(assets)?assets:[assets]).filter(asset=>asset&&!asset.artwork_target),tasks=[];
 for(const asset of rows)tasks.push(await api('metadata/task',{asset:asset.id}));
 await refresh();await openMetadataManager(tasks);
}
