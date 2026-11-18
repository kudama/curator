'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const app=fs.readFileSync(path.join(__dirname,'../curator/static/app.js'),'utf8');
const workbench=fs.readFileSync(path.join(__dirname,'../curator/static/workbench.js'),'utf8');
class Element{
 constructor(tag,text='',cls=''){Object.assign(this,{tag,textContent:text,className:cls,children:[],disabled:false,hidden:false});}
 append(...children){this.children.push(...children);}
 prepend(...children){this.children.unshift(...children);}
 replaceChildren(...children){this.children=children;}
 setAttribute(){}
 querySelectorAll(tag){return descendants(this).filter(e=>e!==this&&e.tag===tag);}
}
function descendants(root){return [root,...root.children.filter(e=>e instanceof Element).flatMap(descendants)];}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function setup(kind='optimize'){
 const elements=new Map(),calls=[],images=[],task={id:'one',version:1,asset:'asset',library:'library',kind,status:'awaiting_review',plan:{},evidence:{},title:'Synthetic video'},asset={id:'asset',library:'library',item:{},technical:{}};
 let open=false;const node=(tag,text,cls)=>{const e=new Element(tag,text,cls);if(tag==='img')images.push(e);return e;};
 const context=vm.createContext({state:{tasks:[task],assets:[asset],config:{}},openedTask:null,inspectorMode:null,selectedAssetId:null,selected:new Set(),URLSearchParams,Promise,encodeURIComponent,setTimeout,clearTimeout,
  $:id=>{if(!elements.has(id))elements.set(id,node('div'));return elements.get(id);},node,
  button:(text,fn,cls)=>{const e=node('button',text,cls);e.onclick=fn;return e;},
  prepareInspector:()=>true,featureAvailable:()=>false,inspectorOpen:()=>open,showInspector:()=>{open=true;},closeInspector:()=>{open=false;context.openedTask=null;},
  taskStatusLabel:s=>s,progressView:()=>node('div'),recommendation:()=>node('div'),taskControls:()=>node('div'),needsQuickTimeRepair:()=>false,
  api:async(endpoint,data)=>{calls.push({endpoint,data});if(endpoint==='handbrake/presets')return {presets:[],executable:'fixture'};return {};},
  refresh:async()=>{},toast:()=>{},confirm:()=>{throw Error('Unexpected confirmation');},portraitVideo:()=>false,
  fileName:()=> 'Synthetic video',metaLine:()=> '1920 × 1080',TASK_LABELS:{upscale:'Upscale video',optimize:'Optimize encoding'},HISTORY_TASK_STATES:new Set(['applied','rejected','cancelled']),
  fileTasks:()=>context.state.tasks,canQueue:t=>t.status==='recommendation',document:{createTextNode:text=>text},thumbnail:()=>node('div')});
 vm.runInContext(app.slice(app.indexOf('async function openTask('),app.indexOf('function renderFilePlan(')),context);
 return {context,task,asset,calls,images,elements,run:code=>vm.runInContext(code,context),all:()=>descendants(elements.get('task-detail')),buttons:()=>descendants(elements.get('task-buttons')),publish:()=>descendants(elements.get('task-buttons')).find(e=>e.textContent==='Accept & publish'),loadImages:()=>{for(const image of images)image.onload();}};
}
test('review loads comparison automatically and waits for all images before one-click publish',async()=>{
 for(const kind of ['optimize','upscale']){
  const h=setup(kind),comparison=deferred(),publication=deferred();h.context.api=async(endpoint,data)=>{h.calls.push({endpoint,data});return endpoint==='comparison'?comparison.promise:publication.promise;};
  const opening=h.run("openTask('one')");assert.equal(h.elements.get('task-detail').children[0].tag,'section');assert.equal(h.calls.length,1);assert.equal(h.calls[0].endpoint,'comparison');assert.equal(h.publish().disabled,true);await h.publish().onclick();assert.equal(h.calls.length,1);
  comparison.resolve({});await tick();assert.equal(h.images.length,8);assert.equal(h.publish().disabled,true);
  for(const image of h.images.slice(0,7))image.onload();await tick();assert.equal(h.publish().disabled,true);h.images[7].onload();await opening;
  assert.equal(h.publish().disabled,false);assert.equal(h.all().some(e=>e.textContent==='Refresh preset list'),false);
  const button=h.publish(),first=button.onclick();await button.onclick();assert.equal(h.calls.filter(c=>c.endpoint==='task/review').length,1);assert.equal(h.calls.at(-1).data.version,1);publication.resolve({});await first;
 }
});
test('failed comparison API and failed image loads stay blocked and offer retry',async()=>{
 const h=setup();let attempt=0;h.context.api=async()=>{if(++attempt===1)throw Error('Source unavailable');return {};};
 await h.run("openTask('one')");assert.equal(h.publish().disabled,true);const retry=h.all().find(e=>e.textContent==='Retry comparison');assert.equal(retry.hidden,false);
 let loading=retry.onclick();await tick();h.images[0].onerror();assert.match(h.images[0].src,/retry=1$/);h.images[0].onerror();await loading;assert.equal(h.publish().disabled,true);assert.equal(retry.hidden,false);
 loading=retry.onclick();await tick();h.loadImages();await loading;assert.equal(h.publish().disabled,false);assert.equal(retry.hidden,true);
});
test('late comparison cannot populate a closed or different inspector',async()=>{
 for(const leave of ["closeInspector()","openedTask='other'","state.tasks[0]={...state.tasks[0],version:2}"]){
  const h=setup(),pending=deferred();h.context.api=()=>pending.promise;const opening=h.run("openTask('one')");h.run(leave);pending.resolve({});await opening;assert.equal(h.images.length,0);assert.equal(h.publish().disabled,true);
 }
});
test('a task changed after image loading is not submitted for publication',async()=>{
 const h=setup(),opening=h.run("openTask('one')");await tick();h.loadImages();await opening;h.task.version=2;
 await assert.rejects(h.publish().onclick(),/Task changed/);assert.equal(h.calls.some(c=>c.endpoint==='task/review'),false);
});
test('preprocessing recommendations retain preset setup',async()=>{
 const h=setup();h.task.status='recommendation';await h.run("openTask('one')");assert.equal(h.calls.some(c=>c.endpoint==='handbrake/presets'),true);assert.equal(h.all().some(e=>e.textContent==='Refresh preset list'),true);assert.equal(h.calls.some(c=>c.endpoint==='comparison'),false);
});
test('ready file overview labels the result without preselecting unrelated work',()=>{
 const h=setup();h.context.state.tasks.push({...h.task,id:'suggestion',kind:'upscale',status:'recommendation'});
 vm.runInContext(workbench.slice(workbench.indexOf('function renderAssetOverview('),workbench.indexOf('function editorTabs(')),h.context);
 h.run('renderAssetOverview(state.assets[0])');assert.equal(h.elements.get('task-kind').textContent,'READY TO PUBLISH');assert.equal(h.context.selected.size,0);assert.ok(h.all().some(e=>e.textContent==='Review & Publish'));assert.ok(h.all().some(e=>e.textContent==='Ready to publish'));
});
test('comparison request timeout becomes a retryable connection error',async()=>{
 const context=vm.createContext({AbortController,setTimeout,clearTimeout,fetch:async(url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'}))))});
 vm.runInContext(app.slice(app.indexOf('async function api('),app.indexOf('async function run(')),context);
 await assert.rejects(vm.runInContext("api('comparison',{id:'one'},{timeout:1})",context),/connection timed out.*retry/);
});
