'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{
 constructor(tag,text='',cls=''){this.tag=tag;this.textContent=text||'';this.children=[];this.className=cls;this.classList={add(){}};this.value='';this.checked=false;this.open=false;}
 set value(value){this._value=String(value);}
 get value(){return this._value;}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(key,value){this[key]=value;}
 addEventListener(){}
 showModal(){this.open=true;}
 close(){this.open=false;}
 remove(){}
}
function harness(snapshot,respond=()=>{}){
 const document={body:new Element('body'),getElementById(){return null;}},calls=[];
 const node=(tag,text,cls)=>new Element(tag,text,cls),button=(text,fn,cls)=>{const el=node('button',text,cls);el.onclick=fn;return el;};
 const context=vm.createContext({window:{addEventListener(){}},document,node,button,URLSearchParams,confirm:()=>true,run:fn=>fn(),api:async(route,data)=>{calls.push({route,data});if(route==='maintenance'&&!data)return structuredClone(snapshot);return respond(route,data);}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../curator/static/maintenance-settings.js'),'utf8'),context);
 function nodes(root=document.body){return [root,...root.children.flatMap(child=>child instanceof Element?nodes(child):[])];}
 const find=(tag,text)=>nodes().find(el=>el.tag===tag&&el.textContent===text);
 return {calls,context,find,nodes,open:()=>vm.runInContext('openMaintenanceSettings()',context)};
}
const snapshot=()=>({policy_accepted:false,machine_paused:true,libraries:[{id:'synthetic:1',title:'Synthetic family',roots:['/synthetic'],paused:false,caps:null}],machine_caps:null,rules:[],cadences:[15,30,60,180,360,1440],receipts:[],limitations:['No automatic publication']});
test('saving disabled draft sends no execution/enable permission and leaves roots explicit',async()=>{
 const h=harness(snapshot());await h.open();await h.find('button','Create disabled rule').onclick();
 assert.equal(h.find('label','/synthetic').children[0].checked,false);
 h.find('label','Rule name').children[0].value='Synthetic rule';h.find('label','/synthetic').children[0].checked=true;
 for(const label of ['Items per run','Items per day'])h.find('label',label).children[0].value='10';
 for(const label of ['Output / scratch space per item','Output / scratch space per day','Minimum free space'])h.find('label',label).children[0].children[0].value='10';
 await h.find('button','Add permitted window').onclick();h.find('label','Monday').children[0].checked=true;h.find('label','Start time').children[0].value='09:00';h.find('label','End time').children[0].value='10:00';
 await h.find('button','Save disabled draft').onclick();const request=h.calls.find(row=>row.data?.operation==='save_rule');
 assert.ok(request);assert.equal(request.data.revision,0);assert.equal(request.data.values.action,'scan');assert.equal(request.data.values.roots.join(','),'/synthetic');assert.equal(request.data.values.options.cadence_minutes,60);assert.ok(!Object.hasOwn(request.data,'enabled'));assert.ok(!h.calls.some(row=>row.data?.operation==='enable'));assert.ok(h.find('button','Create disabled rule'));
});
test('failed enable preview reports reason and never exposes an enable action',async()=>{
 const state=snapshot();state.rules=[{id:'rule',revision:3,values:{name:'Draft',action:'scan',roots:['/synthetic']},enabled:false}];
 const h=harness(state,()=>{throw Error('Policy review pending');});await h.open();await h.find('button','Review enable permission').onclick();
 assert.ok(h.nodes().some(node=>node.textContent==='Policy review pending'));assert.equal(h.find('button','Enable this exact permission'),undefined);assert.ok(!h.calls.some(row=>row.data?.operation==='enable'));
});
test('enable uses only the exact retained preview digest/action and does not unpause queues',async()=>{
 const state=snapshot();state.policy_accepted=true;state.rules=[{id:'rule',revision:3,values:{name:'Draft',action:'scan',roots:['/synthetic']},enabled:false}];
 const h=harness(state,(route,data)=>data.operation==='preview'?{preview:'reviewed-preview',digest:'exact-digest',snapshot:{watermark:7},remaining_manual:['Publication']}:{});await h.open();await h.find('button','Review enable permission').onclick();await h.find('button','Enable this exact permission').onclick();
 const request=h.calls.find(row=>row.data?.operation==='enable');assert.deepEqual(JSON.parse(JSON.stringify(request.data)),{operation:'enable',preview:'reviewed-preview',digest:'exact-digest',action:'scan'});assert.ok(!h.calls.some(row=>/start|resume/.test(row.route)||row.data?.operation==='scope_pause'));
});
test('queue receipt opens its exact retained identity even outside the recent list',async()=>{
 const h=harness(snapshot(),route=>({id:'older-receipt',phase:'failed',inventory:{count:101}}));h.context.id='older-receipt';await vm.runInContext('openMaintenanceSettings(id)',h.context);
 assert.ok(h.calls.some(row=>row.route==='maintenance/receipt?id=older-receipt'));assert.ok(h.find('h3','Maintenance receipt'));assert.ok(h.nodes().some(row=>row.tag==='pre'&&row.textContent.includes('101')));
});
test('consent displays frozen selected roots, windows, options and actual shared cap amounts',async()=>{
 const state=snapshot();state.rules=[{id:'rule',revision:3,values:{name:'Draft',action:'scan',roots:['/wrong-current-root']},enabled:false}];
 const permission={name:'Frozen permission',action:'scan',roots:['/selected-root'],excluded_paths:['/selected-root/private'],excluded_assets:['excluded-item'],timezone:'America/Los_Angeles',windows:[{days:[0],start:'09:00',end:'17:00'}],quiet:[{days:[0],start:'12:00',end:'13:00'}],options:{cadence_minutes:30,inventory_limit:500}};
 const reviewed={preview:'frozen',digest:'digest',snapshot:{permission,allowances:[{scope:'machine',timezone:'UTC',limits:{items_per_run:7,items_per_day:20,output_bytes_per_item:1000,output_bytes_per_day:9000,min_free_bytes:12345}}]},remaining_manual:['Publication']};
 const h=harness(state,()=>reviewed);await h.open();await h.find('button','Review enable permission').onclick();const text=h.nodes().map(node=>node.textContent).join('\n');
 assert.match(text,/Selected allowed roots/);assert.match(text,/\/selected-root/);assert.match(text,/09:00–17:00/);assert.match(text,/12:00–13:00/);assert.match(text,/cadence minutes: 30/);assert.match(text,/Items per run: 7/);assert.match(text,/Minimum free space: 12345 B \(12345 bytes\)/);assert.ok(!text.includes('/wrong-current-root'));
});
test('operational rule summary shows counts, remaining allowance and next eligible scan window',async()=>{
 const state=snapshot();state.rules=[{id:'rule',revision:3,values:{name:'Draft',action:'scan',roots:['/synthetic'],timezone:'UTC'},enabled:false,operational:{counts:{queued:2,running:1,waiting:1,review:3,blocked:4},remaining:[{scope:'machine',daily_items:5,daily_output_bytes:987,day:'2026-11-23',timezone:'UTC',latest_run_items:2}],next_permitted_window:'2026-11-23T09:00:00+00:00',next_scan_window:'2026-11-23T10:00:00+00:00',held:true}}];
 const h=harness(state);await h.open();const text=h.nodes().map(node=>node.textContent).join('\n');assert.match(text,/queued: 2.*running: 1.*review: 3/);assert.match(text,/5 items and 987 B \(987 bytes\) output space left today/);assert.match(text,/Next cadence-eligible scan window:/);assert.ok(!text.includes('2026-11-23T10:00:00'));assert.match(text,/held by a disabled rule, window, maintenance or queue pause/);
});
test('storage units convert exactly and reject blank, fractional bytes or unsafe rounded grants',()=>{
 const h=harness(snapshot());assert.equal(vm.runInContext("maintenanceBytes('1.5','GiB')",h.context),1610612736);assert.equal(vm.runInContext("maintenanceBytes('0','B')",h.context),0);assert.throws(()=>vm.runInContext("maintenanceBytes('','GiB')",h.context),/explicit/);assert.throws(()=>vm.runInContext("maintenanceBytes('0.1','B')",h.context),/whole number/);assert.throws(()=>vm.runInContext("maintenanceBytes('999999999','GiB')",h.context),/too large/);
});
test('excluded item choices use cached titles and retain unavailable saved exclusions internally',async()=>{
 const state=snapshot();state.cached_assets=[{id:'known-id',library:'synthetic:1',title:'Family picnic',available:true}];
 state.rules=[{id:'rule',revision:1,enabled:false,values:{name:'Draft',library:'synthetic:1',action:'scan',roots:['/synthetic'],excluded_paths:[],excluded_assets:['unavailable-id'],limits:{items_per_run:2,items_per_day:3,output_bytes_per_item:2097152,output_bytes_per_day:6291456,min_free_bytes:1048576},timezone:'UTC',windows:[{days:[0],start:'09:00',end:'17:00'}],quiet:[],options:{cadence_minutes:60,inventory_limit:100,page_size:100,max_pages:2,request_timeout_seconds:10,scan_timeout_seconds:120,probe_timeout_seconds:30,response_limit_bytes:1048576,probe_output_bytes:1048576}}}];
 const h=harness(state);await h.open();await h.find('button','Edit draft').onclick();assert.ok(h.find('label','Retained unavailable item 1'));const checkbox=h.find('label','Family picnic').children[0];checkbox.checked=true;checkbox.onchange();await h.find('button','Save disabled draft').onclick();const request=h.calls.find(row=>row.data?.operation==='save_rule');assert.equal(request.data.values.excluded_assets.sort().join(','),'known-id,unavailable-id');const text=h.nodes().map(node=>node.textContent).join('\n');assert.ok(!text.includes('unavailable-id'));assert.ok(!text.includes('known-id'));
});
test('weekday time controls emit original window payload and transport bounds live in Advanced',async()=>{
 const h=harness(snapshot());await h.open();await h.find('button','Create disabled rule').onclick();await h.find('button','Add permitted window').onclick();h.find('label','Tuesday').children[0].checked=true;h.find('label','Start time').children[0].value='18:00';h.find('label','End at midnight').children[0].checked=true;
 assert.ok(h.find('summary','Advanced scan limits'));assert.equal(h.find('label','Permitted windows (JSON)'),undefined);assert.equal(h.find('label','Excluded Curator asset IDs (one per line)'),undefined);
 // Payload assertion uses explicit fields; no JSON editor or default selected weekdays.
 const starts=h.nodes().filter(node=>node['aria-label']==='Permitted windows start time');assert.equal(starts[0].value,'18:00');assert.equal(h.find('label','Monday').children[0].checked,false);
 h.find('label','Rule name').children[0].value='Synthetic';h.find('label','/synthetic').children[0].checked=true;for(const label of ['Items per run','Items per day'])h.find('label',label).children[0].value='3';for(const label of ['Output / scratch space per item','Output / scratch space per day','Minimum free space'])h.find('label',label).children[0].children[0].value='2';await h.find('button','Save disabled draft').onclick();const request=h.calls.find(row=>row.data?.operation==='save_rule');assert.equal(JSON.stringify(request.data.values.windows),'[{"days":[1],"start":"18:00","end":"24:00"}]');assert.equal(request.data.values.limits.min_free_bytes,2147483648);
});
test('an unsafe rounded server allowance cannot be consented through the browser',async()=>{
 const state=snapshot();state.rules=[{id:'rule',revision:1,values:{name:'Draft',action:'scan',roots:[]},enabled:false}];const h=harness(state,()=>({snapshot:{allowances:[{limits:{output_bytes_per_day:Number.MAX_SAFE_INTEGER+1}}]},remaining_manual:[]}));await h.open();await h.find('button','Review enable permission').onclick();assert.equal(h.find('button','Enable this exact permission'),undefined);assert.ok(h.nodes().some(node=>node.textContent.includes('exceeds exact browser precision')));
});
test('next windows format in the rule named timezone and invalid inputs never fall back locally',()=>{
 const h=harness(snapshot());const text=vm.runInContext("maintenanceWindowText('2026-11-23T17:00:00+00:00','America/Los_Angeles')",h.context);assert.match(text,/9:00/);assert.match(text,/PST/);for(const expression of ["maintenanceWindowText('invalid','UTC')","maintenanceWindowText('2026-02-31T17:00:00Z','UTC')","maintenanceWindowText('2026-11-23T24:00:00Z','UTC')","maintenanceWindowText('2026-11-23T17:00:00','UTC')","maintenanceWindowText('2026-11-23T17:00:00Z','invalid-zone')","maintenanceWindowText('2026-11-23T17:00:00Z','')"]){assert.equal(vm.runInContext(expression,h.context),'Unavailable');}
});
