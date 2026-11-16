'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(tag,text='',cls=''){this.tag=tag;this.textContent=text;this.className=cls;this.children=[];this.attrs={};this.value='';this.files=[];this.checked=false;this.disabled=false;}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 setAttribute(k,v){this.attrs[k]=v;}
 focus(){} remove(){} replaceWith(other){this.replacement=other;}
}
const node=(...args)=>new Element(...args);
function all(root){return [root,...root.children.filter(x=>x instanceof Element).flatMap(all)];}
function harness(){let calls=[],changes=0;const c=vm.createContext({URLSearchParams,console,document:{createTextNode:text=>text},node,state:{assets:[],tasks:[]},ARTWORK_LABELS:{background:'Background',cover:'Cover'},prompt:()=> 'New Collection',toast:()=>{},api:async(path,data)=>{calls.push({path,data});return path==='cast/profiles'?{profiles:[]}:{choices:[]};},run:fn=>fn(),button:(text,fn,cls)=>{const e=node('button',text,cls);e.onclick=fn;return e;},openTask:id=>calls.push({review:id}),Date,URL:{createObjectURL:()=>'',revokeObjectURL:()=>{}}});return {c,calls,run:code=>vm.runInContext(code,c),changed:()=>changes++};}
const app=fs.readFileSync(path.join(__dirname,'../curator/static/app.js'),'utf8');
const collections=fs.readFileSync(path.join(__dirname,'../curator/static/collections.js'),'utf8');
const workbench=fs.readFileSync(path.join(__dirname,'../curator/static/workbench.js'),'utf8');
function define(h,start,end){vm.runInContext(app.slice(app.indexOf(start),app.indexOf(end,app.indexOf(start))),h.c);}
test('saved backgrounds remain visible after reopening and offer explicit review',async()=>{
 const h=harness();vm.runInContext(workbench,h.c);h.c.container=node('div');h.c.tasks=[{id:'draft',library:'one',asset:'asset',kind:'artwork',status:'awaiting_review',plan:{kind:'background',candidate:'abc'}},{id:'other',library:'two',asset:'asset',kind:'artwork',status:'awaiting_review',plan:{kind:'background',candidate:'other'}},{id:'applied',library:'one',asset:'asset',kind:'artwork',status:'applied',plan:{kind:'background',candidate:'old'}}];
 h.run("renderArtworkDrafts(container,'one','background','asset',tasks)");const nodes=all(h.c.container);assert.equal(nodes.filter(e=>e.tag==='img').length,1);assert.match(nodes.find(e=>e.tag==='img').src,/photo=abc/);assert.equal(h.calls.length,0);nodes.find(e=>e.tag==='button').onclick();assert.equal(h.calls[0].review,'draft');
 h.run("renderArtworkDrafts(container,'one','background','asset',[])");assert.equal(h.c.container.children.length,0);
});
test('new cast names can be entered and remembered in split metadata view',async()=>{
 const h=harness();define(h,'async function castEditor','async function openFileEditor');h.c.dirty=h.changed;
 const editor=await h.run("castEditor({id:'task'}, {},dirty,{splitPortraits:true})");all(editor.section).find(e=>e.textContent==='Add person').onclick();const nodes=all(editor.section);nodes.find(e=>e.tag==='input'&&e.maxLength===500).value='New Person';const payload=await editor.payload();assert.equal(payload[0].name,'New Person');assert.equal(payload[0].remember,true);assert.ok(nodes.some(e=>e.children.includes(' Remember profile for other titles')));
});
test('portrait library creates a local person without requiring existing credits',async()=>{
 const h=harness();define(h,'async function portraitLibrary','async function mageBatchConsent');const section=await h.run("portraitLibrary('one')");all(section).find(e=>e.attrs['aria-label']==='New person name').value='New Person';await all(section).find(e=>e.textContent==='Save new person').onclick();const call=h.calls.find(c=>c.path==='cast/profile/create');assert.equal(call.data.name,'New Person');assert.equal(section.replacement.open,true);assert.ok(!h.calls.some(c=>c.path==='cast/apply'));
});
test('new collections can be added directly and with Enter, including after enabling folder field',async()=>{
 const h=harness();vm.runInContext(collections,h.c);h.c.input=node('input');h.c.change=h.changed;const picker=h.run("collectionPicker(input,'one',[],change,true)");await new Promise(resolve=>setImmediate(resolve));h.c.input.collectionPicker.setDisabled(false);const add=all(picker).find(e=>e.textContent==='Add new collection');assert.equal(add.disabled,false);add.onclick();assert.deepEqual([...h.c.input.collectionPicker.values()],['New Collection']);const search=all(picker).find(e=>e.type==='search');search.value='Family, 2026';let prevented=false;search.onkeydown({key:'Enter',preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.deepEqual([...h.c.input.collectionPicker.values()],['New Collection','Family, 2026']);assert.equal(h.calls.length,1);
});

test('smart collections stay read-only through both creation controls',async()=>{
 const h=harness();h.c.api=async()=>({choices:[{title:'Smart',smart:true}]});h.c.prompt=()=> 'Smart';vm.runInContext(collections,h.c);h.c.input=node('input');h.c.change=h.changed;const picker=h.run("collectionPicker(input,'one',[],change)");await new Promise(resolve=>setImmediate(resolve));all(picker).find(e=>e.textContent==='Add new collection').onclick();const search=all(picker).find(e=>e.type==='search');search.value='Smart';search.onkeydown({key:'Enter',preventDefault(){}});assert.deepEqual([...h.c.input.collectionPicker.values()],[]);
});

test('folder preview retains selected artwork and metadata regardless of active manager',async()=>{
 const start=app.indexOf(' async function payload(preserve=false)',app.indexOf('async function openFolder(fid)'));
 const source=app.slice(start,app.indexOf('\n recursive.onchange',start));
 for(const manager of ['metadata','artwork']){
  const h=harness();Object.assign(h.c,{folderManager:manager,fields:{studio:{value:'Shared studio'}},enabled:{studio:{checked:true}},useCast:{checked:false},images:{cover:{use:{checked:true},input:{files:[]},photo:'poster'},background:{use:{checked:true},input:{files:[]},photo:'background'},square:{use:{checked:false},input:{files:[]},photo:'square'}},portraitProfiles:[],portraitSelect:{value:''},mode:{value:'fill'},artworkMode:{value:'replace'},recursive:{checked:true},info:{defaults:null},initial:{},current:()=>({profile:'commercial'}),brandToggle:{checked:false}});
  vm.runInContext(source,h.c);
  for(const preserve of [false,true]){
   const value=await h.run('payload('+preserve+')');assert.equal(value.fields.studio,'Shared studio');assert.deepEqual(Object.keys(value.artwork),['cover','background']);assert.equal(value.artwork_mode,'replace');assert.equal(value.mode,'fill');assert.equal(value.recursive,true);
  }
 }
});
