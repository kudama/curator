'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class El{constructor(id){this.id=id;this.hidden=false;this.textContent='';this.children=[];this.dataset={};this.attrs={};this.value='';}
 replaceChildren(...k){this.children=k;}append(...k){this.children.push(...k);}setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}focus(){this.focused=true;}get innerText(){return [this.textContent,...this.children.map(c=>c.innerText??c.textContent??'')].join(' ');}}
function setup({dirty=false,confirmLeave=false}={}){
 const els={},calls=[],tabs=['home','library','history','configuration'].map(t=>{const e=new El('tab-'+t);e.dataset.tab=t;return e;});
 const $=id=>els[id]||(els[id]=new El(id));
 const location={hash:''},replaced=[];
 const context=vm.createContext({URLSearchParams,requestAnimationFrame:f=>f(),calls,replaced,location,
  history:{replaceState:(a,b,h)=>{replaced.push(h);location.hash=h;}},window:{addEventListener(){}},
  document:{body:{dataset:{}},querySelectorAll:s=>s.includes('main-tabs')?tabs:s.includes('queue-lane')?[]:[],querySelector:()=>null},
  $,node:(tag,text,cls)=>{const e=new El();e.tag=tag;if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;},
  state:{libraries:[{id:'films',title:'Films'},{id:'home',title:'Home movies'}],assets:[{id:'a1',library:'films'}],tasks:[
   {id:'t1',library:'films',kind:'artwork',status:'awaiting_review'},{id:'t2',library:'home',kind:'artwork',status:'awaiting_review'},
   {id:'t3',library:'home',kind:'mage_generation',status:'awaiting_review'},{id:'t4',library:'films',kind:'metadata',status:'awaiting_review'},
   {id:'t5',library:'films',kind:'upscale',status:'queued'},{id:'t6',library:'films',kind:'upscale',status:'running'}]},
  screen:'library',libraryId:'films',libraryView:'attention',activeGrouping:'folder',queueLibrary:'all',queueStatus:'all',reviewKind:'all',
  historyView:'jobs',historyScope:'library',historyPeriod:'all',historyStatus:'all',historyLevel:'all',selectedAssetId:null,
  openedTask:null,inspectorDirty:dirty,expandedWaitingQueues:new Set(),waitingSelection:new Set(),
  prepareInspector:()=>{calls.push('prepareInspector');return confirmLeave;},closeInspector:()=>calls.push('closeInspector'),
  setScreen:v=>{calls.push('setScreen:'+v);context.screen=v;return true;},chooseLibrary:id=>{calls.push('chooseLibrary:'+id);context.libraryId=id;context.screen='library';return true;},
  render:()=>calls.push('render'),openConfig:()=>calls.push('openConfig'),openTask:(id,w)=>calls.push('openTask:'+id+':'+w),
  api:()=>{throw Error('navigation must not call the API');}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/navigation.js'),'utf8'),context);
 return {context,calls,replaced,els,location,run:code=>vm.runInContext(code,context)};
}
test('routes parse and format losslessly, and unknown routes fall back to Home',()=>{
 const h=setup();
 for(const hash of ['#/home','#/library/films/files?view=files&group=task','#/library/all/queue?status=review&lane=metadata','#/library/home/artwork?status=review','#/history?view=curator&library=all&period=7','#/configuration/standards/movie','#/configuration/library/films']){
  h.context.hash=hash;assert.equal(h.run('navFormat(navParse(hash))'),hash);}
 h.context.hash='#/library/dev%3Afilms/queue';assert.equal(h.run('navParse(hash).library'),'dev:films');
 h.context.hash='#/nowhere/at/all';assert.equal(h.run('navParse(hash).tab'),'home');assert.equal(h.run('navParse(hash).unknown'),true);
});
test('a queue deep link filters the view, opens the lane, and never starts or changes work',()=>{
 const h=setup();h.run("navApply(navParse('#/library/all/queue?status=review&lane=metadata'))");
 assert.equal(h.context.queueLibrary,'all');assert.equal(h.context.queueStatus,'awaiting_review');
 assert.ok(h.context.expandedWaitingQueues.has('metadata'));assert.ok(h.calls.includes('setScreen:processing'));
 assert.equal(h.els['route-banner'].hidden,false);assert.match(h.els['route-banner'].innerText,/jobs ready to review in Metadata across all libraries/);
 assert.ok(!h.calls.some(c=>String(c).startsWith('openTask')));
});
test('declining to discard unsaved work keeps the current view and address',()=>{
 const h=setup({dirty:true,confirmLeave:false});h.run("navCurrent=navParse('#/library/films/files')");h.location.hash='#/home';
 h.run('navOnHashChange()');
 assert.ok(h.calls.includes('prepareInspector'));assert.ok(!h.calls.some(c=>String(c).startsWith('setScreen')));
 assert.equal(h.location.hash,'#/library/films/files');assert.notEqual(h.context.document.body.dataset.tab,'home');
});
test('a library that is gone falls back to all libraries with a notice and an honest address',()=>{
 const h=setup();h.run("navApply(navParse('#/library/missing/queue'))");
 assert.equal(h.context.queueLibrary,'all');assert.match(h.els['route-notice'].textContent,/no longer connected/);
 assert.equal(h.replaced.at(-1),'#/library/all/queue');
});
test('artwork review links count only that library and open the existing review',()=>{
 const h=setup();h.run("navApply(navParse('#/library/home/artwork?status=review'))");
 assert.ok(h.calls.includes('chooseLibrary:home'));assert.ok(h.calls.includes('setScreen:artwork'));
 assert.match(h.els['route-banner'].innerText,/2 artwork changes are waiting/);
 h.els['route-banner'].children.find(c=>c.tag==='button').onclick();assert.ok(h.calls.includes('openTask:t2:artwork'));
});
test('configuration routes open the existing settings and standards editors only',()=>{
 const h=setup();const opened=[];h.context.openStandardsEditor=t=>opened.push(JSON.stringify(t));
 h.run("navApply(navParse('#/configuration/standards/show'))");h.run("navApply(navParse('#/configuration/library/films'))");h.run("navApply(navParse('#/configuration/connections'))");
 assert.deepEqual(opened,['{"kind":"show"}','{"library":"films"}']);assert.ok(h.calls.includes('openConfig'));
 assert.equal(h.context.document.body.dataset.tab,'configuration');
});
test('the address follows in-app history filters, and the badge counts every review kind',()=>{
 const h=setup();h.run("navApply(navParse('#/history'))");h.context.historyPeriod='30';h.context.historyStatus='failed';h.context.historyScope='all';
 h.run('navAfterRender()');assert.equal(h.location.hash,'#/history?library=all&period=30&status=failed');
 assert.equal(h.els['tab-review-count'].textContent,'4');assert.match(h.els['global-status'].innerText,/1 processing · 0 publishing · 1 waiting/);
});
