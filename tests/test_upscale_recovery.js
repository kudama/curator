'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../curator/static/app.js'),'utf8');
const helper=source.slice(source.indexOf('function renderUpscaleRecovery('),source.indexOf('async function openTask('));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup({needs=true,canReview=true,redo=true}={}){
 const nodes=[],calls=[],task={id:'t1',version:3,status:'blocked'},queue={hidden:false};
 const node=(tag,text,cls)=>{const row={tag,text,cls,children:[],append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},remove(){this.removed=true;}};nodes.push(row);return row;};
 const preview={needs_recovery:needs,can_review:canReview,source_dimensions:[404,720],output_dimensions:[808,1440],target:'1080-class',validation:['Output is below 1080-class target'],token:'exact',redo:{allowed:redo,error:'Unknown geometry',dimensions:[1616,2880],filter:'tvai_up=model=x:scale=4:w=0:h=0',encoding:{topaz_quality:65}}};
 const c=vm.createContext({node,openedTask:'t1',state:{tasks:[task]},button:(label,fn)=>{const n=node('button',label);n.click=fn;return n;},api:async(endpoint,data)=>{calls.push({endpoint,data});return preview;},refresh:async()=>{},closeInspector:()=>{},openTask:async()=>{},toast:()=>{}});
 vm.runInContext(helper,c);const detail=node('section'),actions=node('div');c.detail=detail;c.actions=actions;c.task=task;c.queue=queue;
 vm.runInContext('renderUpscaleRecovery(detail,actions,task,queue)',c);
 return {c,nodes,calls,task,queue,preview};
}
test('below-target choices do not queue, generate or publish before an explicit click',async()=>{
 const h=setup();await tick();assert.equal(h.calls.length,1);assert.equal(h.calls[0].endpoint,'upscale/recovery-preview');assert.equal(h.queue.hidden,true);
 assert.ok(h.nodes.some(n=>n.text==='Review below-target output'));assert.ok(h.nodes.some(n=>n.text==='Prepare 4× redo'));
 const review=h.nodes.find(n=>n.text==='Review below-target output');await review.click();
 assert.equal(h.calls[1].endpoint,'upscale/recovery');assert.equal(h.calls[1].data.action,'review_resolution');assert.equal(h.calls[1].data.token,'exact');
 assert.ok(!h.calls.some(c=>['task/review','task/action','run'].includes(c.endpoint)));
});
test('4x preparation sends the exact preview token once even on repeated clicks',async()=>{
 const h=setup();await tick();let release;h.c.api=async(endpoint,data)=>{h.calls.push({endpoint,data});return new Promise(resolve=>{release=resolve;});};
 const redo=h.nodes.find(n=>n.text==='Prepare 4× redo');const first=redo.click();await redo.click();assert.equal(h.calls.length,2);
 assert.equal(h.calls[1].data.action,'prepare_4x');release({});await first;
});
test('other failures and unknown geometry cannot offer resolution acceptance or a 4x redo',async()=>{
 const h=setup({canReview:false,redo:false});await tick();assert.ok(!h.nodes.some(n=>n.tag==='button'));assert.ok(h.nodes.some(n=>n.text==='Unknown geometry'));
});
test('an ordinary upscale keeps its existing approval controls',async()=>{
 const h=setup({needs:false});await tick();assert.equal(h.queue.hidden,false);assert.ok(!h.nodes.some(n=>n.tag==='button'));
});
test('late preview responses never add controls to a changed task',async()=>{
 const h=setup();h.c.state={tasks:[{...h.task,version:4}]};await tick();assert.ok(!h.nodes.some(n=>n.tag==='button'));assert.equal(h.queue.hidden,false);
});
