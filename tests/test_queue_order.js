'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../curator/static/workbench.js'),'utf8');
function setup(){
 const controls={children:[],append(x){this.children.push(x);},replaceChildren(){this.children=[];}},calls=[];
 const context=vm.createContext({state:{tasks:[{id:'a',version:1,library:'one',status:'queued'},{id:'b',version:2,library:'one',status:'queued'},{id:'run',version:1,library:'one',status:'running'},{id:'other',version:1,library:'two',status:'queued'}]},libraryId:'one',screen:'processing',render(){},toast(){},refresh:async()=>{},api:async(path,data)=>calls.push({path,data}),confirm:()=>false,$:()=>controls,button:(label,fn)=>({label,fn}),node:(tag,text)=>({tag,text}),run:fn=>fn()});
 vm.runInContext(source,context);vm.runInContext('featureAvailable=()=>true',context);
 return {context,controls,calls,run:code=>vm.runInContext(code,context)};
}
test('top/bottom actions retain the selected and unselected relative orders',()=>{
 const w=setup();assert.equal(w.run("moveWaitingOrder(['a','b','c','d'],new Set(['b','d']),'top').join(',')"),'b,d,a,c');
 assert.equal(w.run("moveWaitingOrder(['a','b','c','d'],new Set(['b','d']),'bottom').join(',')"),'a,c,b,d');
});
test('drag order crosses groups but rejects missing and nonwaiting ids',()=>{
 const w=setup();assert.equal(w.run("dropWaitingOrder(['a','b','c'],'c','a').join(',')"),'c,a,b');
 assert.equal(w.run("dropWaitingOrder(['a','b'],'run','a')"),null);assert.equal(w.run("dropWaitingOrder(['a','b'],'a','a')"),null);
});
test('empty queue requires confirmation and submits only the library waiting snapshot',async()=>{
 const w=setup();w.run('renderWaitingControls()');const empty=w.controls.children.find(c=>c.label?.startsWith('Empty waiting queue'));
 await empty.fn();assert.equal(w.calls.length,0);
 w.context.confirm=()=>true;await empty.fn();assert.equal(w.calls.length,1);assert.equal(w.calls[0].path,'queue/change');
 assert.equal(w.calls[0].data.remove.join(','),'a,b');assert.equal(w.calls[0].data.expected.map(x=>x.id+':'+x.version).join(','),'a:1,b:2');
});
