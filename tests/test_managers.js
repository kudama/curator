'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(tag,text='',cls=''){Object.assign(this,{tag,textContent:text,className:cls,children:[],attrs:{},files:[],value:'',hidden:false,disabled:false});}
 append(...items){this.children.push(...items);if(this.tag==='select'&&this.value===''&&items[0])this.value=items[0].value;}
 replaceChildren(...items){this.children=items;}
 setAttribute(key,value){this.attrs[key]=value;}
 get childNodes(){return this.children;}
}
const all=root=>[root,...root.children.filter(n=>n instanceof Element).flatMap(all)];
function setup(){
 const ids=Object.fromEntries(['task-detail','task-buttons','task-title','task-kind','task-reason'].map(k=>[k,new Element('div')]));
 const context=vm.createContext({URLSearchParams,crypto:{randomUUID:()=>Math.random().toString()},node:(...args)=>new Element(...args),$:id=>ids[id],ARTWORK_LABELS:{cover:'Cover'},state:{config:{mage_configured:true,branding_presets:[{id:'gritty',name:'Gritty',details:'Cinematic',background:'dark',typography:'clear'}]}},selectedAssetId:null,openedTask:'parent',inspectorDirty:true,inspectorMode:'artwork-manager',inspectorBack:null,prepareInspector:()=>true,showInspector(){},catalogIndex:()=>({byId:new Map([['a',{id:'a',title:'Title',item:{}}]])}),fileName:a=>a.title,refresh:async()=>{}});
 for(const file of ['client-compat','artwork-manager','metadata-manager'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/'+file+'.js'),'utf8'),context);
 context.button=(label,fn,cls)=>{const result=new Element('button',label,cls);result.onclick=fn;return result;};
 context.asset={id:'a',title:'Title',item:{summary:'Context'}};
 return {context,ids,run:code=>vm.runInContext(code,context),find:label=>Object.values(ids).flatMap(all).find(e=>e.textContent===label)};
}
test('generation close restores parent nodes and unsaved artwork draft',()=>{
 const h=setup(),draft=new Element('canvas'),action=new Element('button','Preview changes');h.ids['task-detail'].append(draft);h.ids['task-buttons'].append(action);h.ids['task-title'].textContent='Original';
 h.run("openManagerGenerate(asset,{},'cover','2:3')");h.run('inspectorBack()');
 assert.equal(h.ids['task-detail'].children[0],draft);assert.equal(h.ids['task-buttons'].children[0],action);assert.equal(h.context.inspectorDirty,true);assert.equal(h.context.openedTask,'parent');assert.equal(h.context.inspectorBack,null);
});
test('a changed setting during pricing cannot authorize an obsolete quote',async()=>{
 const h=setup();let release;const pending=new Promise(resolve=>release=resolve),calls=[];
 h.context.api=async(endpoint,data)=>{calls.push({endpoint,data});if(endpoint==='artwork/plan')return {tasks:[{id:'draft',version:1}]};if(endpoint==='artwork/candidates')return {tasks:[{id:'draft',version:1}]};if(endpoint==='mage/quote')return pending;throw Error('Unexpected '+endpoint);};
 h.run("openManagerGenerate(asset,{},'cover','2:3')");const action=h.find('Check cost').onclick();await new Promise(resolve=>setImmediate(resolve));
 const prompt=all(h.ids['task-detail']).find(e=>e.attrs['aria-label']==='Resolved generation prompt');prompt.value='Changed';prompt.oninput();release({id:'old',total:10});await action;
 assert.equal(h.find('Generate').disabled,true);assert.ok(!calls.some(c=>c.endpoint==='mage/check'||c.endpoint==='mage/authorize'));
});
test('monthly allowance blocks generation and exact batch limit is priced',async()=>{
 const h=setup(),calls=[];h.context.api=async(endpoint,data)=>{calls.push({endpoint,data});return endpoint==='mage/check'?{balance_status:'available',balance:100,budget:{limit:20,committed:18}}:endpoint==='mage/quote'?{id:'quote',total:7}:{tasks:[{id:'draft',version:1}]};};
 h.run("openManagerGenerate(asset,{},'cover','2:3')");const budget=all(h.ids['task-detail']).find(e=>e.attrs['aria-label']==='Batch Gems budget');budget.value='8';budget.oninput();await h.find('Check cost').onclick();
 assert.equal(calls.find(c=>c.endpoint==='mage/quote').data.batch_limit,8);assert.equal(h.find('Generate').disabled,true);assert.ok(all(h.ids['task-buttons']).some(e=>e.textContent.includes('Over monthly allowance')));assert.ok(!calls.some(c=>c.endpoint==='mage/authorize'));
});
test('queued metadata opens an explanation instead of editable controls',async()=>{
 const h=setup();h.context.api=()=>{throw Error('No read or write needed');};await h.run("openMetadataManager([{id:'task',asset:'a',version:2,status:'queued'}])");
 assert.ok(h.ids['task-detail'].children[0].textContent.includes('already queued'));assert.ok(h.find('Close'));assert.ok(!h.find('Preview changes'));
});

test('retrying partial artwork preview reuses drafts already retained',async()=>{
 const h=setup(),calls=[];h.context.screen='artwork';h.context.render=()=>{};h.context.state.libraries=[];
 h.context.ARTWORK_LABELS={cover:'Cover',background:'Background',square:'Square',logo:'Logo'};
 Element.prototype.classList={toggle(){}};
 h.context.managerArtworkCard=(asset,task,kind)=>({section:new Element('section'),asset,kind,dirty:()=>true,ready:()=>true,encoded:()=>asset.id+'-candidate',original:async()=>null,ratio:()=> '2:3'});
 h.context.assets=[{id:'a',library:'one',rating_key:'1',title:'First',item:{}},{id:'b',library:'one',rating_key:'2',title:'Second',item:{}}];
 let failed=false;h.context.api=async(endpoint,data)=>{calls.push(data.assets[0]);if(data.assets[0]==='b'&&!failed){failed=true;throw Error('Synthetic connection failure');}return {tasks:[{id:data.assets[0],title:data.assets[0],version:1,plan:{kind:'cover',candidate:'photo'}}]};};
 await h.run('openArtworkManager(assets)');await h.find('Preview changes').onclick();assert.deepEqual(calls,['a','b']);await h.find('Preview changes').onclick();
 assert.deepEqual(calls,['a','b','b']);assert.ok(h.find('Approve & queue 2 artwork changes'));
});

test('native logo candidate becomes a ready draft through a CSP-compatible blob URL',async()=>{
 const h=setup();h.context.state.libraries=[];h.context.ARTWORK_LABELS.logo='Logo';let revoked=[];
 h.context.atob=s=>Buffer.from(s,'base64').toString('binary');h.context.Blob=Blob;h.context.URL={createObjectURL:()=> 'blob:local-logo',revokeObjectURL:v=>revoked.push(v)};
 const previous=Object.getOwnPropertyDescriptor(Element.prototype,'src');
 Object.defineProperty(Element.prototype,'src',{configurable:true,set(value){this._src=value;if(value.startsWith('blob:')){this.naturalWidth=600;this.naturalHeight=180;queueMicrotask(()=>this.onload?.());}},get(){return this._src||'';}});
 Element.prototype.getContext=()=>({clearRect(){},drawImage(){},getImageData:()=>({data:new Uint8Array([255,255,255,128])})});Element.prototype.classList={add(){},toggle(){}};Element.prototype.style={};
 let changed=0;h.context.changed=()=>changed++;
 try{const card=h.run("managerArtworkCard(asset,{},'logo',changed)");await card.setCandidate('aGVsbG8=','original');assert.equal(card.dirty(),true);assert.equal(card.ready(),true);assert.equal(card.canvas.width,600);assert.equal(card.canvas.hidden,false);assert.equal(await card.original(),'original');assert.equal(changed,1);}finally{delete Element.prototype.src;if(previous)Object.defineProperty(Element.prototype,'src',previous);}
});

test('Mage settings preserve an unavailable saved model and use model-specific resolutions',()=>{
 const h=setup();vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/mage-settings.js'),'utf8'),h.context);
 h.run("mageDiscovery={model_catalog:[{id:'mango-v2',name:'Mango 2',group:'Mango',supported:true,resolutions:['2K','3K','4K']},{id:'mango-v4',name:'Mango 4',group:'Mango',supported:true,resolutions:['1K','2K']}]}");
 h.context.model=new Element('select');h.context.resolution=new Element('select');h.context.resolution.value='4K';h.context.model.value='mango-v4';h.run('syncMageResolution(model,resolution)');assert.deepEqual(h.context.resolution.children.map(e=>e.value),['1K','2K']);assert.equal(h.context.resolution.value,'1K');
 h.run("fillMageModels(model,'retired-model')");assert.equal(h.context.model.value,'retired-model');assert.equal(h.context.model.children.at(-1).disabled,true);
});

test('metadata and artwork panels open without secure-context crypto APIs',async()=>{
 const h=setup();delete h.context.crypto;h.context.state.libraries=[];h.context.screen='artwork';h.context.render=()=>{};Element.prototype.classList={add(){},toggle(){}};
 await h.run("openMetadataManager([{id:'task',asset:'a',version:1,status:'queued'}])");assert.equal(h.context.inspectorMode,'metadata-manager');assert.ok(h.find('Close'));
 h.context.managerArtworkCard=(asset,task,kind)=>({section:new Element('section'),asset,kind,dirty:()=>false,ready:()=>false});
 await h.run('openArtworkManager([asset])');assert.equal(h.context.inspectorMode,'artwork-manager');assert.ok(h.find('Preview changes'));
});

test('draft identities use getRandomValues on HTTP without randomUUID',()=>{
 const h=setup();let called=0;h.context.crypto={getRandomValues(bytes){bytes.fill(++called);return bytes;}};
 const a=h.run('clientId()'),b=h.run('clientId()');assert.match(a,/^[a-f0-9]{32}$/);assert.notEqual(a,b);assert.equal(called,2);
});

test('Generate stays compact and requires a valid current quote',async()=>{
 const h=setup(),calls=[];h.context.api=async(endpoint,data)=>{calls.push(endpoint);return endpoint==='mage/check'?{balance_status:'available',balance:1000,budget:{limit:200,committed:0}}:endpoint==='mage/quote'?{id:'quote',total:135}:{tasks:[{id:'draft',version:1}]};};
 h.run("openManagerGenerate(asset,{},'cover','2:3')");assert.equal(h.find('Generate').disabled,true);
 const count=all(h.ids['task-detail']).find(e=>e.attrs['aria-label']==='Number of options');count.value='1';count.onchange();await h.find('Check cost').onclick();
 assert.equal(h.find('Generate').disabled,false);assert.ok(all(h.ids['task-buttons']).some(e=>e.textContent.includes('1 option · 135 Gems')));assert.ok(!calls.includes('mage/authorize'));
 count.value='2';count.onchange();assert.equal(h.find('Generate').disabled,true);
 const links=all(h.ids['task-detail']).find(e=>e.className==='manager-reference-actions');assert.deepEqual(links.children.filter(e=>e.tag==='button').map(e=>e.textContent),['Use current artwork','Choose a source frame','No reference']);
});

test('Generate approves once, starts only the artwork queue and removes the form',async()=>{
 const h=setup();vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/mage-settings.js'),'utf8'),h.context);
 const calls=[];h.context.api=async(endpoint,data)=>{calls.push({endpoint,data});return {queued:2};};h.context.toast=()=>{};h.context.showMageGenerationQueue=()=>calls.push({endpoint:'queue-view'});
 h.ids['task-buttons'].append(new Element('button','Generate'));h.context.detail=h.ids['task-detail'];h.context.actions=h.ids['task-buttons'];await h.run("generateMageQuote('priced-quote',detail,actions)");
 assert.deepEqual(calls.map(c=>c.endpoint),['mage/authorize','run','queue-view']);assert.equal(calls[0].data.consent,true);assert.equal(calls[1].data.kind,'mage_generation');assert.equal(calls[1].data.scope,'all');assert.ok(!all(h.ids['task-buttons']).some(e=>e.textContent==='Generate'));
});

test('queue start failure retains approval and never resubmits the generation',async()=>{
 const h=setup();vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/mage-settings.js'),'utf8'),h.context);let approvals=0,warning='';h.context.api=async(endpoint)=>{if(endpoint==='mage/authorize'){approvals++;return {queued:1};}throw Error('Temporary disconnect');};h.context.toast=message=>warning=message;h.context.showMageGenerationQueue=()=>{};h.context.detail=h.ids['task-detail'];h.context.actions=h.ids['task-buttons'];
 await h.run("generateMageQuote('priced-quote',detail,actions)");assert.equal(approvals,1);assert.match(warning,/approval saved/);assert.ok(!all(h.ids['task-buttons']).some(e=>e.textContent==='Generate'));
});

test('generation metadata checks flag missing descriptions and raw episode/file titles',()=>{
 const h=setup();vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/mage-settings.js'),'utf8'),h.context);
 h.context.example={title:'Summer journey',item:{summary:'A family trip through the mountains.'}};assert.equal(h.run('generationMetadataIssues(example).length'),0);
 h.context.example={title:'Series s2023e01.mp4',item:{summary:''}};assert.equal(h.run('generationMetadataIssues(example).length'),2);
 h.context.example={title:'Alex',artwork_target:'person',item:{}};assert.equal(h.run('generationMetadataIssues(example).length'),0);
});

test('selecting a family reference uses the exact style template and removing it restores text-only wording',async()=>{
 const h=setup();h.context.asset.title='Family picnic';h.context.asset.item.summary='Our dog at the park';
 h.context.fileBase64=async()=> 'aGVsbG8=';h.context.artworkBlobURL=()=> 'blob:family-reference';h.context.URL={revokeObjectURL(){}};
 h.run("openManagerGenerate(asset,{},'cover','16:9')");
 const prompt=all(h.ids['task-detail']).find(e=>e.attrs['aria-label']==='Resolved generation prompt'),image=all(h.ids['task-detail']).find(e=>e.className==='manager-reference'),upload=all(h.ids['task-detail']).find(e=>e.attrs['aria-label']==='Upload reference image');image.src='';
 assert.ok(prompt.value.startsWith('Create cover artwork for Family picnic'));
 upload.files=[{name:'family-dog.png'}];await upload.onchange();assert.equal(prompt.value,'re-imagine this image in style guidance Cinematic');
 const calls=[];h.context.api=async(endpoint,data)=>{calls.push({endpoint,data});return endpoint==='mage/check'?{balance_status:'available',balance:1000,budget:{}}:endpoint==='mage/quote'?{id:'quote',total:12}:{tasks:[{id:'draft',version:1}]};};await h.find('Check cost').onclick();const planned=calls.find(c=>c.endpoint==='artwork/plan').data;assert.equal(planned.overrides.prompt,prompt.value);assert.equal(planned.references.length,1);
 h.context.state.config.branding_presets[0].details='Watercolor';const style=all(h.ids['task-detail']).find(e=>e.attrs['aria-label']==='Style guide');style.onchange();assert.equal(prompt.value,'re-imagine this image in style guidance Watercolor');
 h.find('No reference').onclick();assert.ok(prompt.value.startsWith('Create cover artwork for Family picnic'));
 prompt.value='My custom pet portrait';prompt.oninput();await upload.onchange();assert.equal(prompt.value,'My custom pet portrait');h.find('No reference').onclick();assert.equal(prompt.value,'My custom pet portrait');
});

test('an over-budget cost check keeps the estimate visible and generation disabled',async()=>{
 const h=setup(),calls=[];
 h.context.api=async(endpoint)=>{calls.push(endpoint);if(endpoint==='mage/quote')throw Error('Estimated cost: 270 Gems for 2 options. Curator batch budget: 200 Gems (70 Gems over budget).');return {tasks:[{id:'draft',version:1}]};};
 h.run("openManagerGenerate(asset,{},'cover','2:3')");await h.find('Check cost').onclick();
 const message=all(h.ids['task-buttons']).find(e=>e.className==='muted editor-status').textContent;
 assert.ok(message.includes('270 Gems'));assert.ok(message.includes('200 Gems'));assert.ok(message.includes('70 Gems over budget'));assert.equal(h.find('Generate').disabled,true);assert.ok(!calls.includes('mage/authorize'));
});
