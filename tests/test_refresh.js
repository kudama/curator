'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function setup(){
 const status={},timers=[],calls=[],notices=[];let fetcher=async()=>({ok:true,json:async()=>({reset:true,revision:'r',state:{assets:[],tasks:[],libraries:[]}})});
 const c=vm.createContext({state:{assets:[{id:'old'}],tasks:[{id:'old-task'}],libraries:[]},libraryId:null,serviceRestarting:false,mutationEpoch:0,AbortController,Date,
  $:()=>status,render:()=>calls.push('render'),updateServiceControls(){},syncCatalog:async()=>{},toast:()=>notices.push('toast'),fetch:(...args)=>fetcher(...args),
  setTimeout:(fn,ms)=>{const timer={fn,ms};timers.push(timer);return timer;},clearTimeout:t=>{if(t)t.cleared=true;}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/refresh.js'),'utf8'),c);
 return {c,status,timers,calls,notices,setFetch:f=>{fetcher=f;},run:s=>vm.runInContext(s,c)};
}
const pending=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const response=(revision,state)=>({ok:true,json:async()=>({reset:true,revision,state})});
test('background failures use one status and back off; recovery clears it',async()=>{
 const h=setup();h.setFetch(async()=>{throw Error('Failed to fetch');});
 for(let i=0;i<5;i++)await h.run('backgroundRefresh()');
 assert.equal(h.status.hidden,false);assert.match(h.status.textContent,/reconnecting/);assert.equal(h.notices.length,0);
 assert.deepEqual(h.timers.filter(t=>t.ms!==25000).map(t=>t.ms),[8000,16000,32000,60000,60000]);
 h.setFetch(async()=>response('ok',{assets:[],tasks:[],libraries:[]}));await h.run('backgroundRefresh()');
 assert.equal(h.status.hidden,true);assert.equal(h.run('refreshFailures'),0);assert.equal(h.timers.at(-1).ms,4000);
});
test('slow refresh calls share a flight, then perform one trailing read',async()=>{
 const h=setup(),p=pending();let count=0,active=0,max=0;
 h.setFetch(async()=>{count++;active++;max=Math.max(max,active);if(count===1)await p.promise;active--;return response('r'+count,{assets:[],tasks:[],libraries:[]});});
 const first=h.run('refresh()'),second=h.run('refresh()'),third=h.run('refresh()');assert.equal(first,second);assert.equal(second,third);assert.equal(count,1);
 p.resolve();await first;assert.equal(count,2);assert.equal(max,1);
});
test('response crossing a user mutation is discarded before render',async()=>{
 const h=setup(),p=pending();let count=0;
 h.setFetch(async()=>{count++;if(count===1)await p.promise;return response('r'+count,{assets:[{id:count===1?'stale':'fresh'}],tasks:[],libraries:[]});});
 const flight=h.run('refresh()');h.c.mutationEpoch+=2;p.resolve();await flight;
 assert.equal(h.c.state.assets[0].id,'fresh');assert.equal(h.calls.length,1);
});
test('incremental changes preserve untouched records and update removals and order',()=>{
 const h=setup();h.c.state={assets:[{id:'a',title:'keep'},{id:'b'},{id:'remove'}],tasks:[{id:'t',draft:'saved'}],libraries:[]};
 const keep=h.c.state.assets[0];h.c.delta={reset:false,revision:'next',fields:{queue_running:true},changes:{assets:{upsert:[{id:'b',title:'changed'},{id:'c'}],removed:['remove'],order:['c','b','a']}}};
 const next=h.run('applyStateUpdate(delta)');assert.equal(next.assets[2],keep);assert.equal(next.assets[1].title,'changed');assert.equal(next.tasks,h.c.state.tasks);assert.equal(next.queue_running,true);assert.equal(next.assets.length,3);
});
test('refresh timeout aborts its request and leaves existing state intact',async()=>{
 const h=setup();h.setFetch((url,opts)=>new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(Error('aborted')))));
 const flight=h.run('refresh()');h.timers.find(t=>t.ms===25000).fn();await assert.rejects(flight,/aborted/);assert.equal(h.c.state.assets[0].id,'old');assert.equal(h.status.hidden,false);
});
