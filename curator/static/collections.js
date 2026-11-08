'use strict';
function collectionNames(values){
 if(!Array.isArray(values))return [];
 const seen=new Set();return values.filter(value=>typeof value==='string'&&value.trim()).map(value=>value.trim()).filter(value=>{const key=value.toLocaleLowerCase();if(seen.has(key))return false;seen.add(key);return true;});
}
function metadataListValue(input){return input.collectionPicker?input.collectionPicker.values():[...new Set(input.value.split(',').map(x=>x.trim()).filter(Boolean))];}
function collectionPicker(input,library,initial,onChange,disabled=false,field='collection'){
 const plural={collection:'Collections',genre:'Tags / genres',label:'Labels'}[field],singular={collection:'collection',genre:'tag / genre',label:'label'}[field];
 let chosen=collectionNames(initial),catalog=[],loaded=false,loading=false,error='',generation=0;
 const box=node('fieldset',undefined,'collection-picker');box.setAttribute('aria-label',plural);box.disabled=disabled;
 const selected=node('div',undefined,'collection-chips'),search=node('input');search.type='search';search.placeholder='Search or add a '+singular+'…';search.setAttribute('aria-label','Search '+plural.toLowerCase());
 const results=node('div',undefined,'collection-results'),status=node('p','','muted');status.setAttribute('role','status');
 const refresh=button('Refresh '+plural.toLowerCase(),load,'text-button');box.append(selected,search,results,status,refresh);
 const key=value=>value.toLocaleLowerCase();
 function notify(){input.value=JSON.stringify(chosen);render();onChange();}
 function add(value){const exact=catalog.find(row=>!row.smart&&key(row.title)===key(value));chosen=collectionNames([...chosen,exact?.title||value.trim()]);search.value='';notify();search.focus();}
 function render(){
  selected.replaceChildren();for(const name of chosen){const chip=node('span',undefined,'collection-chip');chip.append(node('span',name));const remove=button('×',()=>{chosen=chosen.filter(value=>key(value)!==key(name));notify();});remove.setAttribute('aria-label','Remove '+singular+' '+name);chip.append(remove);selected.append(chip);}
  results.replaceChildren();const query=search.value.trim(),matching=catalog.filter(row=>!query||key(row.title).includes(key(query)));
  for(const row of matching.slice(0,50)){const has=chosen.some(name=>key(name)===key(row.title)),option=button((has?'✓ ':'')+row.title+(row.smart?' · Smart':''),()=>{if(has){chosen=chosen.filter(name=>key(name)!==key(row.title));notify();}else add(row.title);},has?'collection-option selected':'collection-option');option.disabled=row.smart||(!has&&chosen.length>=200);option.setAttribute('aria-pressed',String(has));if(row.smart)option.title='Smart collection membership follows its Plex rules';results.append(option);}
  const exact=catalog.find(row=>key(row.title)===key(query));
  if(loaded&&query&&!exact&&!chosen.some(name=>key(name)===key(query))){const create=button('New '+singular+': '+query,()=>add(query),'collection-new');create.disabled=query.length>500||chosen.length>=200;results.append(create);}
  status.textContent=loading?'Loading '+plural.toLowerCase()+' from Plex…':error?'Could not load '+plural.toLowerCase()+': '+error+' Existing selections are kept.':query&&exact?.smart?'Smart collection membership follows its Plex rules.':!loaded?plural+' unavailable.':matching.length>50?'Showing 50 of '+matching.length+' matches. Type to narrow the list.':chosen.some(name=>!catalog.some(row=>key(row.title)===key(name)))?'New names are saved when metadata is applied.':catalog.length+' '+plural.toLowerCase()+' in this library'+(!catalog.length?' · Type a name to add one.':'.');
  refresh.disabled=loading;
 }
 async function load(){const request=++generation;loading=true;error='';render();try{const response=await api('library/metadata-choices?'+new URLSearchParams({library,field}));if(request!==generation)return;if(!Array.isArray(response.choices))throw Error('Invalid metadata choices response');const byName=new Map();for(const row of response.choices){if(typeof row.title!=='string'||!row.title.trim())continue;const previous=byName.get(key(row.title));if(!previous||previous.smart&&!row.smart)byName.set(key(row.title),row);}catalog=[...byName.values()].sort((a,b)=>a.title.localeCompare(b.title));loaded=true;}catch(failure){if(request!==generation)return;error=failure.message==='Not found'?'Restart Curator to enable metadata discovery.':failure.message;loaded=false;}finally{if(request===generation){loading=false;render();}}}
 search.oninput=render;
 input.type='hidden';input.value=JSON.stringify(chosen);input.collectionPicker={values:()=>[...chosen],setValues:values=>{chosen=collectionNames(values);input.value=JSON.stringify(chosen);render();},setDisabled:value=>box.disabled=value};
 render();load();return box;
}
