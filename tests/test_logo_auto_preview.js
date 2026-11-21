'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
class Element{
 constructor(tag,text='',cls=''){this.tag=tag;this.textContent=text;this.className=cls;this.children=[];this.attrs={};this.value='';this.disabled=false;this.hidden=false;this.isConnected=true;this.style={};this.files=[];this.classList={toggle(){}};}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 setAttribute(k,v){this.attrs[k]=v;}
}
function all(root){return [root,...root.children.filter(e=>e instanceof Element).flatMap(all)];}
const source=fs.readFileSync(path.join(__dirname,'../curator/static/artwork-editors.js'),'utf8');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup({available=true,fonts=['Arial','Baskerville']}={}){
 const detail=new Element('div'),actions=new Element('div'),timers=new Map(),calls=[],pending=[];let nextTimer=0;
 const c=vm.createContext({URLSearchParams,console,openedTask:'logo',inspectorDirty:false,inspectorBack:null,
 node:(...args)=>new Element(...args),button:(text,fn,cls)=>{const b=new Element('button',text,cls);b.onclick=fn;return b;},
 setTimeout:fn=>{timers.set(++nextTimer,fn);return nextTimer;},clearTimeout:id=>timers.delete(id),
 api:async(route,data)=>{if(route==='artwork/fonts')return {available,fonts,reason:'Fonts unavailable'};calls.push({route,data});return {id:'job-'+calls.length};}
 });
 vm.runInContext(source,c);
 c.preservedArtworkPanel=()=>()=>{};c.artworkPanel=()=>({token:'logo',detail,actions});c.prepareInspector=()=>true;
 c.retainedArtworkImage=photo=>{const image=new Element('img');image.photo=photo;return image;};
 c.encodedArtwork=async photo=>'encoded-'+photo;
 c.waitArtworkRender=(job,note)=>new Promise((resolve,reject)=>pending.push({job,note,resolve,reject}));
 const control=label=>all(detail).find(e=>e.attrs['aria-label']===label),action=label=>all(actions).find(e=>e.textContent===label);
 return {c,detail,actions,calls,pending,control,action,open:options=>c.openLocalLogo({id:'asset',title:'Test title'},options),
 flush:async()=>{const batch=[...timers.values()];timers.clear();batch.forEach(fn=>fn());await settle();},
 complete:async(index,photo)=>{pending[index].resolve({photo,width:640,height:120});await settle();},
 image:()=>all(detail).find(e=>e.tag==='img'),timerCount:()=>timers.size};
}
test('opening text lettering previews automatically and never applies the draft',async()=>{
 const h=setup();let applied=0;await h.open({apply:()=>applied++});assert.equal(h.calls.length,0);assert.equal(h.action('Preview logo').hidden,true);
 await h.flush();assert.equal(h.calls.length,1);assert.equal(h.calls[0].data.font,'Arial');assert.equal(h.calls[0].data.mode,'logo_text');assert.equal(h.action('Use logo draft').disabled,true);
 await h.complete(0,'first');assert.equal(h.image().photo,'first');assert.equal(h.action('Use logo draft').disabled,false);assert.equal(applied,0);
});
test('rapid font, text and color changes coalesce into the latest preview',async()=>{
 const h=setup();await h.open();const font=h.control('Logo font'),title=h.control('Logo title text'),color=h.control('Logo text color');
 font.value='Baskerville';font.onchange();title.value='Latest title';title.oninput();color.value='#abcdef';color.oninput();assert.equal(h.timerCount(),1);
 await h.flush();assert.equal(h.calls.length,1);assert.equal(h.calls[0].data.font,'Baskerville');assert.equal(h.calls[0].data.text,'Latest title');assert.equal(h.calls[0].data.color,'#abcdef');
});
test('edits during a render suppress its result and serialize the newest preview',async()=>{
 const h=setup();await h.open();await h.flush();h.control('Logo font').value='Baskerville';h.control('Logo font').onchange();await h.flush();assert.equal(h.calls.length,1);
 h.pending[0].note.textContent='Old progress';assert.notEqual(h.action('Old progress')?.textContent,'Old progress');
 await h.complete(0,'obsolete');assert.equal(h.image(),undefined);assert.equal(h.action('Use logo draft').disabled,true);
 await h.flush();assert.equal(h.calls.length,2);assert.equal(h.calls[1].data.font,'Baskerville');await h.complete(1,'latest');assert.equal(h.image().photo,'latest');
});
test('an edit immediately invalidates an earlier usable draft; blank text renders nothing',async()=>{
 const h=setup();await h.open();await h.flush();await h.complete(0,'first');const title=h.control('Logo title text');title.value=' ';title.oninput();assert.equal(h.action('Use logo draft').disabled,true);await h.flush();assert.equal(h.calls.length,1);
});
test('leaving the editor cancels pending preview submission and ignores an in-flight result',async()=>{
 const h=setup();await h.open();h.c.openedTask='elsewhere';await h.flush();assert.equal(h.calls.length,0);
 const active=setup();await active.open();await active.flush();active.detail.isConnected=false;await active.complete(0,'closed');assert.equal(active.image(),undefined);
});
test('render errors offer explicit retry and reuse the existing queued job',async()=>{
 const h=setup();await h.open();await h.flush();h.pending[0].reject(Error('Temporarily unavailable'));await settle();const retry=h.action('Preview logo');assert.equal(retry.hidden,false);assert.equal(retry.disabled,false);
 const retrying=retry.onclick();await settle();assert.equal(h.calls.length,1);assert.equal(h.pending[1].job.id,h.pending[0].job.id);await h.complete(1,'recovered');await retrying;assert.equal(h.image().photo,'recovered');
});
test('imported logo cleanup still requires an explicit preview',async()=>{
 const h=setup();await h.open({sourcePhoto:'original'});await h.flush();assert.equal(h.calls.length,0);const preview=h.action('Preview logo');assert.equal(preview.hidden,false);
 h.control('Background tolerance percent').value='5';h.control('Background tolerance percent').oninput();await h.flush();assert.equal(h.calls.length,0);
 const rendering=preview.onclick();await settle();assert.equal(h.calls[0].data.mode,'logo_cleanup');assert.equal(h.calls[0].data.fuzz,5);await h.complete(0,'clean');await rendering;
});
test('unavailable or empty host font catalog submits no automatic render',async()=>{
 for(const options of [{available:false},{fonts:[]}]){const h=setup(options);await h.open();h.control('Logo title text').oninput();await h.flush();assert.equal(h.calls.length,0);assert.equal(h.action('Use logo draft').disabled,true);}
});
