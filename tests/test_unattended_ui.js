'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../curator/static/workbench.js'),'utf8');
class Element{constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.disabled=false;this.dataset={};}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}setAttribute(){}}
function setup(){
 const elements=new Map(),calls=[],messages=[],storage=new Map(),notifications=[];let permissions=0;
 class Notification{static permission='granted';static async requestPermission(){permissions++;return 'granted';}constructor(title,options){notifications.push({title,...options});}}
 const context=vm.createContext({state:{tasks:[],libraries:[],global_queue:[]},libraryId:'one',screen:'processing',queueStatus:'all',inspectorMode:null,openedTask:null,selected:new Set(),
  $:id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},node:(tag,text)=>new Element(tag,text),button:(text,fn)=>{const e=new Element('button',text);e.onclick=fn;return e;},
  api:async(endpoint,data)=>{calls.push({endpoint,data});return {waiting:2,running:0,file_waiting:0,limits:{optimize:2},volumes:[],issues:[],processing_eta_seconds:null,estimate_note:'Measured estimates only'};},
  formatBytes:String,TASK_LABELS:{optimize:'Encoding',upscale:'Upscale'},run:fn=>fn(),refresh:async()=>{},render:()=>{},toast:text=>messages.push(text),Notification,
  window:{isSecureContext:true,focus(){}},localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
  document:{querySelectorAll:()=>[],getElementById:()=>({append(){}})}});
 vm.runInContext(source,context);context.prepareInspector=()=>true;context.showInspector=()=>{};context.closeInspector=()=>{};
 return {context,calls,elements,messages,storage,notifications,permissions:()=>permissions,run:code=>vm.runInContext(code,context)};
}
test('readiness does not start work until the explicit start action, which submits once',async()=>{
 const h=setup();await h.run('showRunReadiness()');assert.deepEqual(h.calls.map(c=>c.endpoint),['run/readiness']);
 const start=h.elements.get('task-buttons').children.find(e=>e.textContent==='Start unattended run');assert.ok(start);
 await start.onclick();await start.onclick();assert.equal(h.calls.filter(c=>c.endpoint==='run').length,1);assert.equal(h.calls[1].data.scope,'all');
});
test('failed readiness offers retry and never starts an unreviewed run',async()=>{
 const h=setup();h.context.api=async()=>{throw Error('Unavailable');};await h.run('showRunReadiness()');
 assert.match(h.elements.get('task-detail').children[0].textContent,/Could not check readiness/);assert.equal(h.elements.get('task-buttons').children[0].textContent,'Retry checks');
});
test('notifications suppress historical and duplicate completion and never ask permission automatically',()=>{
 const h=setup();h.storage.set('curator.run-notifications','enabled');h.context.summaries=[{id:'old',title:'Run',phase:'complete',counts:{total:1,ready:1}}];h.run('notifyRunChanges(summaries)');assert.equal(h.notifications.length,0);
 h.context.state.tasks=[{status:'queued'}];h.context.summaries.push({id:'new',title:'Run',phase:'complete',counts:{total:2,ready:2}});h.run('notifyRunChanges(summaries)');h.run('notifyRunChanges(summaries)');
 assert.equal(h.notifications.length,1);assert.match(h.notifications[0].body,/2 ready for review/);assert.match(h.notifications[0].body,/remains in Queue/);assert.equal(h.permissions(),0);
});
test('browser notification permission is requested only through the explicit control',async()=>{
 const h=setup();assert.equal(h.permissions(),0);await h.run('enableRunNotifications()');assert.equal(h.permissions(),1);assert.equal(h.storage.get('curator.run-notifications'),'enabled');
 h.context.window.isSecureContext=false;await h.run('enableRunNotifications()');assert.equal(h.permissions(),1);assert.match(h.messages.at(-1),/unavailable here/);
});
test('batch defaults are remembered only for libraries with successfully queued jobs',async()=>{
 const h=setup();h.context.state.tasks=[{id:'a',library:'one',version:1,kind:'optimize',status:'recommendation',plan:{}},{id:'b',library:'two',version:1,kind:'optimize',status:'recommendation',plan:{}}];h.context.canQueue=()=>true;
 h.context.api=async(endpoint,data)=>{h.calls.push({endpoint,data});if(data.id==='b')throw Error('Changed');return {};};
 await h.run("queueTaskRows(state.tasks,{handbrake_preset:'Chosen',remember_preset:true})");const defaults=h.calls.filter(c=>c.endpoint==='processing-defaults');assert.equal(defaults.length,1);assert.equal(defaults[0].data.library,'one');assert.equal(defaults[0].data.values.handbrake_preset,'Chosen');
});

test('queue empty state hides inapplicable selection and pause controls',()=>{
 const h=setup();h.context.featureAvailable=()=>true;h.run('renderWaitingControls()');
 const labels=h.elements.get('queue-actions').children.map(e=>e.textContent);
 assert.deepEqual(labels,['Processing limits']);
});
test('recent activity is collapsed and has no notification or stale failure shortcuts',()=>{
 const h=setup();h.context.featureAvailable=()=>true;h.context.state.run_summaries=[{id:'past',title:'Original cleanup',phase:'needs_attention',counts:{total:9,failed:9}}];h.run('renderRunSummaries()');
 const details=h.elements.get('run-summaries').children[0];assert.equal(details.tag,'details');assert.notEqual(details.open,true);
 assert.equal(details.children[0].textContent,'Recent activity (1)');
 const text=JSON.stringify(details);assert.doesNotMatch(text,/Enable browser|Open needs attention/);
});
test('processing tab counts publication alongside running jobs',()=>{
 const h=setup();h.context.state.tasks=[{library:'one',status:'publishing'},{library:'one',status:'running'},{library:'one',status:'blocked'}];h.run('renderQueueStatusTabs()');
 assert.ok(h.elements.get('queue-status-tabs').children.some(e=>e.textContent==='Processing 2'));
});
