'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(tag,text='',cls=''){Object.assign(this,{tag,textContent:text,className:cls,children:[],attrs:{},value:'',hidden:false,disabled:false});}
 append(...items){this.children.push(...items);if(this.tag==='select'&&this.value===''&&items[0])this.value=items[0].value;}
 replaceChildren(...items){this.children=items;}
 setAttribute(key,value){this.attrs[key]=value;}
 get childNodes(){return this.children;}
}
const all=root=>[root,...root.children.filter(n=>n instanceof Element).flatMap(all)];
function setup(){
 const ids=Object.fromEntries(['task-detail','task-buttons','task-title','task-kind','task-reason'].map(k=>[k,new Element('div')]));
 const context=vm.createContext({URLSearchParams,crypto:{randomUUID:()=>Math.random().toString()},node:(...args)=>new Element(...args),$:id=>ids[id],ARTWORK_LABELS:{cover:'Cover'},state:{config:{mage_configured:true,branding_presets:[{id:'gritty',name:'Gritty',details:'Cinematic',background:'dark',typography:'clear'}]}},selectedAssetId:null,openedTask:'parent',inspectorDirty:true,inspectorMode:'artwork-manager',inspectorBack:null,prepareInspector:()=>true,showInspector(){},catalogIndex:()=>({byId:new Map([['a',{id:'a',title:'Title',item:{}}]])}),fileName:a=>a.title,refresh:async()=>{}});
 for(const file of ['artwork-manager','metadata-manager'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/'+file+'.js'),'utf8'),context);
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
 assert.equal(h.find('Generate options').disabled,true);assert.ok(!calls.some(c=>c.endpoint==='mage/check'||c.endpoint==='mage/authorize'));
});
test('monthly allowance blocks generation and exact batch limit is priced',async()=>{
 const h=setup(),calls=[];h.context.api=async(endpoint,data)=>{calls.push({endpoint,data});return endpoint==='mage/check'?{balance_status:'available',balance:100,budget:{limit:20,committed:18}}:endpoint==='mage/quote'?{id:'quote',total:7}:{tasks:[{id:'draft',version:1}]};};
 h.run("openManagerGenerate(asset,{},'cover','2:3')");const budget=all(h.ids['task-detail']).find(e=>e.attrs['aria-label']==='Batch Gems budget');budget.value='8';budget.oninput();await h.find('Check cost').onclick();
 assert.equal(calls.find(c=>c.endpoint==='mage/quote').data.batch_limit,8);assert.equal(h.find('Generate 2 options · 7 Gems').disabled,true);assert.ok(all(h.ids['task-buttons']).some(e=>e.textContent.includes('Over monthly allowance')));assert.ok(!calls.some(c=>c.endpoint==='mage/authorize'));
});
test('queued metadata opens an explanation instead of editable controls',async()=>{
 const h=setup();h.context.api=()=>{throw Error('No read or write needed');};await h.run("openMetadataManager([{id:'task',asset:'a',version:2,status:'queued'}])");
 assert.ok(h.ids['task-detail'].children[0].textContent.includes('already queued'));assert.ok(h.find('Close'));assert.ok(!h.find('Preview changes'));
});
