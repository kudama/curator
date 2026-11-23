'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class El{constructor(id){this.id=id;this.hidden=false;this.textContent='';this.children=[];this.dataset={};this.attrs={};this.value='';}
 replaceChildren(...k){this.children=k;}append(...k){this.children.push(...k);}setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}focus(){this.focused=true;}get innerText(){return [this.textContent,...this.children.map(c=>c.innerText??c.textContent??'')].join(' ');}}
function setup({dirty=false,confirmLeave=false,open=false}={}){
 const els={},calls=[],tabs=['home','library','history','configuration'].map(t=>{const e=new El('tab-'+t);e.dataset.tab=t;return e;});
 const $=id=>els[id]||(els[id]=new El(id));
 const location={hash:''},replaced=[];
 const context=vm.createContext({URLSearchParams,requestAnimationFrame:f=>f(),calls,replaced,location,
  history:{replaceState:(a,b,h)=>{replaced.push(h);location.hash=h;}},window:{addEventListener(){}},
  document:{body:{dataset:{}},activeElement:null,querySelectorAll:s=>s.includes('main-tabs')?tabs:s.includes('queue-lane')?[]:[],querySelector:()=>null},
  $,node:(tag,text,cls)=>{const e=new El();e.tag=tag;if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;},
  state:{libraries:[{id:'films',title:'Films'},{id:'home',title:'Home movies'}],assets:[{id:'a1',library:'films'}],tasks:[
   {id:'t1',library:'films',kind:'artwork',status:'awaiting_review'},{id:'t2',library:'home',kind:'artwork',status:'awaiting_review'},
   {id:'t3',library:'home',kind:'mage_generation',status:'awaiting_review'},{id:'t4',library:'films',kind:'metadata',status:'awaiting_review'},
   {id:'t5',library:'films',kind:'upscale',status:'queued'},{id:'t6',library:'films',kind:'upscale',status:'running'}]},
  screen:'library',libraryId:'films',libraryView:'attention',activeGrouping:'folder',queueLibrary:'all',queueStatus:'all',reviewKind:'all',
  historyView:'jobs',historyScope:'library',historyPeriod:'all',historyStatus:'all',historyLevel:'all',selectedAssetId:null,
  openedTask:open||dirty?'t4':null,inspectorDirty:dirty,selected:new Set(),searchText:'',expandedWaitingQueues:new Set(),waitingSelection:new Set(),
  prepareInspector:()=>{calls.push('prepareInspector');return confirmLeave;},closeInspector:()=>{calls.push('closeInspector');context.openedTask=null;context.inspectorDirty=false;},
  // Like the real setScreen: changing screen clears search and selection.
  setScreen:v=>{calls.push('setScreen:'+v);if(context.screen!==v){context.searchText='';context.selected.clear();}context.screen=v;return true;},chooseLibrary:id=>{calls.push('chooseLibrary:'+id);context.libraryId=id;context.screen='library';return true;},
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
 assert.equal(h.els['tab-review-count'].textContent,'4'); // 3 artwork + 1 metadata
 assert.match(h.els['global-status'].innerText,/1 processing · 0 publishing · 1 waiting/);
});
test('a busy or unsaved inspector blocks every departure before anything changes',()=>{
 for(const route of ['#/home','#/history?period=7','#/configuration','#/library/all/queue']){
  const h=setup({open:true,confirmLeave:false});h.context.historyPeriod='all';
  assert.equal(h.run(`navApply(navParse('${route}'))`),false,route);
  assert.equal(h.context.document.body.dataset.tab,undefined,route);assert.equal(h.context.historyPeriod,'all',route);
  assert.ok(!h.calls.includes('closeInspector'),route);assert.ok(!h.calls.some(c=>String(c).startsWith('setScreen')),route);
 }
 const ok=setup({open:true,confirmLeave:true});assert.equal(ok.run("navApply(navParse('#/home'))"),true);
 assert.deepEqual(ok.calls.slice(0,2),['prepareInspector','closeInspector']);
});
// A representative editor with the real choose() contract: switching asks once, and declining or a
// running save keeps the current page.
function editor(h,{page='type:movie',dirty=true,busy=false,answer=false}={}){
 const e={page,prompts:0,dialog:{open:true,close(){this.open=false;}},
  canLeave(){if(busy)return false;if(!dirty)return true;e.prompts++;return answer;},
  choose(next){if(next===e.page)return true;if(!e.canLeave())return false;e.page=next;dirty=false;return true;}};
 h.context.standardsEditor=e;h.context.openStandardsEditor=t=>e.choose(t.library?'library:'+t.library:'type:'+(t.kind||'movie'));return e;
}
test('an unsaved standards editor must agree before any other route',()=>{
 const h=setup(),e=editor(h);h.run("navApply(navParse('#/configuration/standards/movie'))");
 const before=h.location.hash;
 assert.equal(h.run("navApply(navParse('#/home'))"),false);assert.equal(e.dialog.open,true);assert.equal(h.context.document.body.dataset.tab,'configuration');
 e.canLeave=()=>true;assert.equal(h.run("navApply(navParse('#/home'))"),true);assert.equal(e.dialog.open,false);
 assert.notEqual(before,'#/home');
});
test('declining a dirty standards switch, or a running save, keeps the editor page, tab and address',()=>{
 for(const options of [{answer:false},{busy:true}]){
  const h=setup(),e=editor(h,options);h.run("navCurrent=navParse('#/configuration/standards/movie')");h.context.document.body.dataset.tab='configuration';h.location.hash='#/configuration/standards/movie';
  for(const hash of ['#/configuration/standards/show','#/configuration/library/films']){
   h.location.hash=hash;h.run('navOnHashChange()');
   assert.equal(e.page,'type:movie',JSON.stringify(options));assert.equal(h.location.hash,'#/configuration/standards/movie');
   assert.equal(h.run('navFormat(navCurrent)'),'#/configuration/standards/movie');
  }
 }
});
test('accepting a dirty standards switch asks exactly once and commits the route',()=>{
 const h=setup(),e=editor(h,{answer:true});h.run("navCurrent=navParse('#/configuration/standards/movie')");h.context.document.body.dataset.tab='configuration';
 assert.equal(h.run("navApply(navParse('#/configuration/library/films'))"),true);
 assert.equal(e.page,'library:films');assert.equal(e.prompts,1);assert.equal(h.run('navFormat(navCurrent)'),'#/configuration/library/films');
});
test('the dimension filter is set before the first files render, and cleared before other workspaces render',()=>{
 const h=setup(),order=[];let filter='old';
 h.context.setStandardDimensionFilter=d=>{filter=d;order.push('set:'+d);};
 const real=h.context.setScreen,choose=h.context.chooseLibrary;
 h.context.setScreen=v=>{order.push('render:'+v+':'+filter);return real(v);};
 h.context.chooseLibrary=id=>{order.push('render:choose:'+filter);return choose(id);};
 h.run("navApply(navParse('#/library/home/files?dimension=cast'))");
 assert.equal(order[0],'set:cast');assert.ok(order.slice(1).every(e=>!e.startsWith('render')||e.endsWith(':cast')),order.join());
 order.length=0;h.run("navApply(navParse('#/library/films/queue'))");
 assert.equal(order[0],'set:null');assert.ok(order.slice(1).every(e=>!e.startsWith('render')||e.endsWith(':null')),order.join());
});
test('Home and dimension links use #110 helpers when present',()=>{
 const h=setup(),filters=[];h.context.renderHomeSummary=()=>{h.calls.push('summary');};h.context.setStandardDimensionFilter=d=>filters.push(d);
 h.run("navApply(navParse('#/home'))");assert.ok(h.calls.includes('summary'));
 h.run("navApply(navParse('#/library/films/files?dimension=metadata'))");assert.equal(h.els['route-notice'].hidden,true);
 h.run("navApply(navParse('#/library/all/queue'))");assert.deepEqual(filters,['metadata',null]);
});
test('returning by tab restores search, selections and the item, dropping work that has gone',()=>{
 const h=setup();h.run("navApply(navParse('#/library/films/files?view=files'))");
 h.context.searchText='sample';h.context.selected.add('t4');h.context.selected.add('gone');h.context.selectedAssetId='a1';
 h.run("navApply(navParse('#/home'),{fromLink:false})");h.context.screen='history';h.context.searchText='';h.context.selected.clear();
 h.run("navApply(navParse('#/library/films/files?view=files'),{fromLink:false})");
 assert.equal(h.context.searchText,'sample');assert.equal(h.els['file-search'].value,'sample');
 assert.deepEqual([...h.context.selected],['t4']);assert.equal(h.context.selectedAssetId,'a1');
 // A new link replaces the context instead of reviving it.
 h.run("navApply(navParse('#/home'),{fromLink:false})");h.run("navApply(navParse('#/library/films/files?view=completed'))");
 assert.equal(h.context.searchText,'');
});
test('Home sends each review family to its own destination, artwork per library',()=>{
 const h=setup();h.run("navApply(navParse('#/home'))");
 const links=h.els['home-page'].children.find(c=>c.className==='home-links').children.map(a=>[a.children[0].textContent,a.children[1].textContent,a.href]);
 assert.deepEqual(links.slice(1,5),[
  ['Results to publish','0 results wait for your comparison','#/library/all/review'],
  ['Metadata suggestions','1 suggestion waits in the Metadata lane','#/library/all/queue?status=review&lane=metadata'],
  ['Artwork · Films','1 change waits for approval','#/library/films/artwork?status=review'],
  ['Artwork · Home movies','2 changes wait for approval','#/library/home/artwork?status=review']]);
});
test('a standard-dimension link says the filter is not available instead of pretending',()=>{
 const h=setup();h.run("navApply(navParse('#/library/films/files?dimension=metadata'))");
 assert.match(h.els['route-notice'].textContent,/not available yet/);assert.equal(h.els['route-banner'].hidden,true);
});
