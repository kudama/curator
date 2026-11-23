'use strict';
// Main navigation (#108): Home, Library Manager, History and Configuration as hash routes over the
// existing workspaces. Following a route only changes what is shown: it never starts, saves, publishes
// or pays for anything. Unsaved work is protected by the existing inspector check.
const NAV_TABS=['home','library','history','configuration'];
const NAV_LIBRARY_VIEWS=['files','queue','review','filemanagement','artwork'];
const NAV_QUEUE_STATUS={all:'all',running:'running',queued:'queued',review:'awaiting_review',attention:'attention'};
const NAV_LANES={upscale:'Upscaling',optimize:'Encoding',file_operations:'File operations',mage_generation:'Artwork generation',metadata:'Metadata'};
const NAV_REVIEW_KINDS=['all','upscale','optimize','join','preview_render'];
const NAV_ARTWORK_KINDS=new Set(['artwork','mage_generation','portrait']);
const NAV_METADATA_KINDS=new Set(['metadata','home','folder_metadata']);
const NAV_STATUS_TEXT={all:'all jobs',running:'processing jobs',queued:'waiting jobs',review:'jobs ready to review',attention:'jobs needing attention'};
const NAV_VIEW_TEXT={attention:'items needing attention',files:'all files',completed:'completed items'};
const navMemory={},navContext={};let navApplying=false,navCurrent=null,navNotice='';

function navParse(hash){
 const raw=String(hash||'').replace(/^#\/?/,''),[pathPart,queryPart='']=raw.split('?'),parts=pathPart.split('/').filter(Boolean).map(p=>{try{return decodeURIComponent(p);}catch(error){return p;}});
 const query={};for(const [k,v] of new URLSearchParams(queryPart))query[k]=v;
 const tab=parts[0]||'home';
 if(!NAV_TABS.includes(tab))return {tab:'home',parts:[],query:{},unknown:true};
 if(tab==='library')return {tab,library:parts[1]||null,view:NAV_LIBRARY_VIEWS.includes(parts[2])?parts[2]:'files',parts,query,unknown:Boolean(parts[2])&&!NAV_LIBRARY_VIEWS.includes(parts[2])};
 if(tab==='configuration')return {tab,section:parts.slice(1).join('/')||'',parts,query};
 return {tab,parts,query};
}
function navFormat(route){
 const q=new URLSearchParams(Object.entries(route.query||{}).filter(([,v])=>v!==undefined&&v!==null&&v!=='')).toString(),suffix=q?'?'+q:'';
 if(route.tab==='library')return '#/library/'+encodeURIComponent(route.library||'all')+'/'+(route.view||'files')+suffix;
 if(route.tab==='configuration')return '#/configuration'+(route.section?'/'+route.section.split('/').map(encodeURIComponent).join('/'):'')+suffix;
 return '#/'+route.tab+suffix;
}
// The route that describes what is on screen now, so the address and tab memory follow in-app clicks.
function navCurrentRoute(){
 const tab=document.body.dataset.tab||'library';
 if(tab==='home')return {tab:'home'};
 if(tab==='configuration')return navCurrent?.tab==='configuration'?navCurrent:{tab:'configuration'};
 if(screen==='history'){const query={};if(historyView!=='jobs')query.view=historyView;query.library=historyScope==='all'?'all':libraryId||'all';if(historyPeriod!=='all')query.period=historyPeriod;if(historyStatus!=='all')query.status=historyStatus;if(historyLevel!=='all')query.level=historyLevel;return {tab:'history',query};}
 if(screen==='processing'){const status=Object.entries(NAV_QUEUE_STATUS).find(([,v])=>v===queueStatus)?.[0]||'all';return {tab:'library',library:queueLibrary||'all',view:'queue',query:status==='all'?{}:{status}};}
 if(screen==='review')return {tab:'library',library:queueLibrary||'all',view:'review',query:reviewKind==='all'?{}:{kind:reviewKind}};
 if(screen==='filemanagement'||screen==='artwork')return {tab:'library',library:libraryId||'all',view:screen,query:{}};
 const query={};if(libraryView!=='attention')query.view=libraryView;if(activeGrouping!=='folder')query.group=activeGrouping;
 return {tab:'library',library:libraryId||'all',view:'files',query};
}
function navCarry(route){
 const previous=navCurrent;if(!previous||previous.tab!==route.tab||previous.library!==route.library||previous.view!==route.view)return route;
 const query={...route.query};for(const key of ['lane','asset','dimension','status'])if(previous.query?.[key]&&!(key in query))query[key]=previous.query[key];
 if(route.view==='queue'&&query.status&&NAV_QUEUE_STATUS[query.status]!==queueStatus)delete query.status;
 return {...route,query};
}
function navSaveContext(tab){
 if(tab!=='library'&&tab!=='history')return;
 const pane=document.querySelector('.file-pane');
 navContext[tab]={screen,search:searchText,selected:[...selected],waiting:[...waitingSelection],scroll:pane?pane.scrollTop:0,asset:selectedAssetId};
}
function navRestoreContext(tab){
 const saved=navContext[tab];if(!saved||saved.screen!==screen)return;
 // Only ids that still exist come back; inspector drafts are never revived.
 const tasks=new Set(state.tasks.map(t=>t.id));
 searchText=saved.search;if($('file-search'))$('file-search').value=saved.search;
 selected.clear();for(const id of saved.selected)if(tasks.has(id))selected.add(id);
 waitingSelection.clear();for(const id of saved.waiting)if(tasks.has(id))waitingSelection.add(id);
 if(saved.asset&&state.assets.some(a=>a.id===saved.asset))selectedAssetId=saved.asset;
 render();
 const pane=document.querySelector('.file-pane');if(pane)requestAnimationFrame(()=>{pane.scrollTop=saved.scroll;});
}
function navSetTab(tab){
 document.body.dataset.tab=tab;
 for(const link of document.querySelectorAll('#main-tabs [data-tab]')){const on=link.dataset.tab===tab;if(on)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
 $('home-page').hidden=tab!=='home';$('configuration-page').hidden=tab!=='configuration';
}
function navBanner(text,clearRoute){
 const banner=$('route-banner');if(!banner)return;
 if(!text){banner.hidden=true;banner.replaceChildren();return;}
 const message=node('p',text),clear=node('a','Show everything');clear.href=navFormat(clearRoute);banner.replaceChildren(message,clear);banner.hidden=false;
}
function navFocus(tab){
 const target=tab==='home'?$('home-heading'):tab==='configuration'?$('configuration-heading'):$('library-title');
 if(target){target.tabIndex=-1;target.focus({preventScroll:true});}
}
function navLibraryExists(id){return state.libraries.some(l=>l.id===id);}
function navPendingArtwork(library){return state.tasks.filter(t=>t.status==='awaiting_review'&&!t.deleted&&NAV_ARTWORK_KINDS.has(t.kind)&&(!library||t.library===library));}
const NAV_RESULT_KINDS=new Set(['upscale','optimize','join','preview_render']);
function navReviewFamilies(){
 const waiting=state.tasks.filter(t=>t.status==='awaiting_review'&&!t.deleted),artwork={};
 for(const t of waiting)if(NAV_ARTWORK_KINDS.has(t.kind))artwork[t.library]=(artwork[t.library]||0)+1;
 return {results:waiting.filter(t=>NAV_RESULT_KINDS.has(t.kind)).length,metadata:waiting.filter(t=>NAV_METADATA_KINDS.has(t.kind)).length,artwork};
}
function navReviewCount(){const f=navReviewFamilies();return f.results+f.metadata+Object.values(f.artwork).reduce((a,b)=>a+b,0);}

// Apply a route to the existing workspaces. Returns false when the user kept unsaved work.
// The existing checks decide whether the current view may be left: an open inspector (unsaved or
// mid-save) and the standards editor. Nothing about navigation changes until they agree.
function navGuard(route){
 if(navCurrent&&navFormat(route)===navFormat(navCurrent))return true;
 const open=typeof inspectorOpen==='function'?inspectorOpen():Boolean(openedTask);
 if(open){if(!prepareInspector())return false;closeInspector(true);}
 if(typeof standardsEditor!=='undefined'&&standardsEditor?.dialog?.open){
  const section=route.tab==='configuration'?route.section||'':'',target=section.startsWith('standards/')?'type:'+section.slice(10):section.startsWith('library/')?'library:'+section.slice(8):null;
  // Switch the open editor to the exact target first; only a real switch lets the route commit.
  if(target){if(!standardsEditor.choose(target))return false;}
  else{if(!standardsEditor.canLeave())return false;standardsEditor.dialog.close();}
 }
 return true;
}
function navApply(route,{fromLink=true}={}){
 const current=document.body.dataset.tab||'library';if(current!==route.tab)navSaveContext(current);
 if(!navGuard(route))return false;
 navApplying=true;let notice=route.unknown?'That link is not available any more; showing the nearest view.':'';
 try{
  if(route.tab==='home'){navSetTab('home');renderHome();navBanner('');}
  else if(route.tab==='configuration'){navSetTab('configuration');renderConfiguration(route);navBanner('');}
  else if(route.tab==='history'){
   const q=route.query||{};
   if(q.library&&q.library!=='all'){if(navLibraryExists(q.library)){if(q.library!==libraryId&&!chooseLibrary(q.library))return false;historyScope='library';}else notice='That library is no longer connected; showing all libraries.';}
   if(q.library==='all'||notice)historyScope='all';
   historyView=['jobs','curator'].includes(q.view)?q.view:'jobs';historyPeriod=['all','1','7','30'].includes(q.period)?q.period:'all';historyStatus=q.status||'all';historyLevel=q.level||'all';
   if(!setScreen('history'))return false;navSetTab('history');
   const filtered=Object.keys(q).some(k=>k!=='library'&&q[k]&&q[k]!=='all');navBanner(fromLink&&filtered?'Opened from a link: History is filtered by the address. Filters only change what you see.':'',{tab:'history'});
  }else{
   navSetTab('library');const q=route.query||{};let id=route.library;
   // A new link defines the view on its own; returning by tab restores the saved context instead.
   if(fromLink){searchText='';if($('file-search'))$('file-search').value='';}
   if(id&&id!=='all'&&!navLibraryExists(id)){notice='That library is no longer connected; showing all libraries.';id='all';}
   const scoped=id&&id!=='all';
   const view=route.view||'files';
   // #110's helper stores the validated dimension; set it before anything below renders, so the
   // first render already uses it (other workspaces clear it).
   if(typeof setStandardDimensionFilter==='function')setStandardDimensionFilter(view==='files'?q.dimension||null:null);
   if(scoped&&id!==libraryId&&!chooseLibrary(id))return false;
   if(view==='files'){
    if(!scoped&&!libraryId&&state.libraries.length&&!chooseLibrary(state.libraries[0].id))return false;
    libraryView=['attention','files','completed'].includes(q.view)?q.view:'attention';activeGrouping=['folder','task','movie'].includes(q.group)?q.group:'folder';
    if($('group-by'))$('group-by').value=activeGrouping;if(!setScreen('library'))return false;
    if(q.asset&&state.assets.some(a=>a.id===q.asset&&a.library===libraryId)){selectedAssetId=q.asset;render();}
    // Without #110's helper, say dimension filtering is unavailable rather than pretend.
    if(typeof setStandardDimensionFilter!=='function'&&q.dimension)notice='Filtering by standard dimension is not available yet; showing '+(NAV_VIEW_TEXT[libraryView]||'items')+'.';
    navBanner(fromLink&&(q.view||q.asset)?'Opened from a link: showing '+(NAV_VIEW_TEXT[libraryView]||'items')+'. Filters only change what you see.':'',{tab:'library',library:id||'all',view:'files'});
   }else if(view==='queue'){
    queueLibrary=scoped?id:'all';queueStatus=NAV_QUEUE_STATUS[q.status]||'all';waitingSelection.clear();
    const lane=Object.hasOwn(NAV_LANES,q.lane||'')?q.lane:null;if(lane)expandedWaitingQueues.add(lane);
    if(!setScreen('processing'))return false;
    if(lane)requestAnimationFrame(()=>[...document.querySelectorAll('.queue-lane')].find(l=>l.getAttribute('aria-label')===NAV_LANES[lane])?.scrollIntoView({block:'nearest'}));
    navBanner(fromLink&&(q.status||q.lane)?'Opened from a link: showing '+(NAV_STATUS_TEXT[q.status]||'all jobs')+(lane?' in '+NAV_LANES[lane]:'')+(scoped?' in this library':' across all libraries')+'. The filter only changes what you see; it does not change or start any job.':'',{tab:'library',library:scoped?id:'all',view:'queue'});
   }else if(view==='review'){
    queueLibrary=scoped?id:'all';reviewKind=NAV_REVIEW_KINDS.includes(q.kind)?q.kind:'all';
    if(!setScreen('review'))return false;navBanner('');
   }else{
    if(!scoped){notice='Choose a library first; '+(view==='artwork'?'artwork':'file management')+' belongs to one library.';if(!libraryId&&state.libraries.length&&!chooseLibrary(state.libraries[0].id))return false;}
    if(!setScreen(view))return false;
    const pending=view==='artwork'&&q.status==='review'?navPendingArtwork(libraryId):[];
    if(view==='artwork'&&q.status==='review')navArtworkBanner(pending);else navBanner('');
   }
  }
  navNotice=notice;const status=$('route-notice');if(status){status.textContent=notice;status.hidden=!notice;}
  navCurrent=route;
  // A fallback shows a different view than the link asked for: make the address say what is shown.
  if(notice){const shown=route.tab==='home'?{tab:'home'}:navCurrentRoute();navCurrent=navParse(navFormat(shown));history.replaceState(null,'',navFormat(shown));}
  navMemory[route.tab==='home'||route.tab==='configuration'?route.tab:document.body.dataset.tab]=location.hash||navFormat(navCurrent);
  if(!fromLink&&(route.tab==='library'||route.tab==='history'))navRestoreContext(route.tab);
  navUpdateBadges();navFocus(route.tab);
  return true;
 }finally{navApplying=false;}
}
function navArtworkBanner(pending){
 const banner=$('route-banner');if(!banner)return;
 if(!pending.length){navBanner('No artwork changes are waiting for approval in this library.',{tab:'library',library:libraryId,view:'artwork'});return;}
 const open=node('button',pending.length===1?'Open it':'Open the next one','text-button');open.onclick=()=>openTask(pending[0].id,'artwork');
 const clear=node('a','Show everything');clear.href=navFormat({tab:'library',library:libraryId,view:'artwork'});
 banner.replaceChildren(node('p',pending.length+' artwork '+(pending.length===1?'change is':'changes are')+' waiting for your approval in this library. Approving still happens in its review.'),open,clear);banner.hidden=false;
}
// Called after every workbench render: keep the address and tab memory in step with in-app clicks.
function navAfterRender(){
 const tab=document.body.dataset.tab;if(tab)navUpdateBadges();if(navApplying||!tab||tab==='home'||tab==='configuration')return;
 if(screen==='history'&&tab!=='history')navSetTab('history');else if(screen!=='history'&&tab==='history')navSetTab('library');
 const route=navCarry(navCurrentRoute()),hash=navFormat(route);navMemory[document.body.dataset.tab]=hash;
 if(location.hash!==hash){navCurrent=navParse(hash);history.replaceState(null,'',hash);}
}
function navUpdateBadges(){
 const count=navReviewCount(),badge=$('tab-review-count');if(badge){badge.textContent=String(count);badge.hidden=!count;badge.title=count+' ready to review';}
 const status=$('global-status');if(status){const running=state.tasks.filter(t=>t.status==='running').length,publishing=state.tasks.filter(t=>t.status==='publishing').length,waiting=state.tasks.filter(t=>t.status==='queued').length,link=node('a','View queue');link.href='#/library/all/queue';status.replaceChildren(node('span',running+' processing · '+publishing+' publishing · '+waiting+' waiting'),node('span','Queue runs across all libraries','muted'),link);}
}
function renderHome(){
 if(typeof renderHomeSummary==='function')return renderHomeSummary(); // Home content (#110), when loaded.
 const page=$('home-page');if(!page)return;
 const f=navReviewFamilies(),plural=(n,one,many)=>n+' '+(n===1?one:many);
 const links=[['Library Manager','Browse and fix items in a library',navFormat({tab:'library',library:libraryId||'all',view:'files'})],
  ['Results to publish',plural(f.results,'result waits','results wait')+' for your comparison',navFormat({tab:'library',library:'all',view:'review'})],
  ['Metadata suggestions',plural(f.metadata,'suggestion waits','suggestions wait')+' in the Metadata lane',navFormat({tab:'library',library:'all',view:'queue',query:{status:'review',lane:'metadata'}})],
  ...Object.entries(f.artwork).map(([lib,n])=>['Artwork · '+(state.libraries.find(l=>l.id===lib)?.title||'Library'),plural(n,'change waits','changes wait')+' for approval',navFormat({tab:'library',library:lib,view:'artwork',query:{status:'review'}})]),['Queue','Everything waiting or running, across all libraries',navFormat({tab:'library',library:'all',view:'queue'})],['History','What Curator and you have done',navFormat({tab:'history'})],['Configuration','Connections, processing defaults and standards',navFormat({tab:'configuration'})]];
 const grid=node('div',undefined,'home-links');for(const [title,detail,href] of links){const a=node('a',undefined,'home-link');a.href=href;a.append(node('strong',title),node('span',detail,'muted'));grid.append(a);}
 const heading=node('h1','Home');heading.id='home-heading';
 page.replaceChildren(node('div','HOME','eyebrow'),heading,node('p','Nothing on Home starts a job or publishes media; every item opens the matching work.','muted'),grid,node('p','Library health, new arrivals and work accomplished will appear here.','muted'));
}
function renderConfiguration(route){
 const page=$('configuration-page');if(!page)return;
 const heading=node('h1','Configuration');heading.id='configuration-heading';
 const sections=node('div',undefined,'home-links'),standards=typeof openStandardsEditor==='function';
 const entry=(title,detail,action,available=true)=>{const b=node('button',undefined,'home-link');b.type='button';b.append(node('strong',title),node('span',detail,'muted'));b.onclick=action;b.disabled=!available;sections.append(b);};
 entry('Connections & tools','Plex, tools and global thresholds',()=>openConfig());
 entry('Processing defaults','Encode and upscale presets',()=>openConfig());
 entry('Standards by Plex type','Movies · TV Shows · Other Videos',()=>navOpenStandards({kind:'movie'}),standards);
 entry('Library overrides','Per-library differences',()=>navOpenStandards(libraryId?{library:libraryId}:{kind:'movie'}),standards);
 page.replaceChildren(node('div','CONFIGURATION','eyebrow'),heading,node('p','Opening a section changes nothing until you save it there.','muted'),sections);
 const section=route.section||'';
 if(section==='connections'||section==='processing')openConfig();
 else if(section.startsWith('standards/'))navOpenStandards({kind:section.slice(10)});
 else if(section.startsWith('library/'))navOpenStandards({library:section.slice(8)});
 if(!standards)page.append(node('p','Standards editing is not available in this build.','muted'));
}
function navOpenStandards(target){if(typeof openStandardsEditor!=='function')return;openStandardsEditor(target);}
function navTabClick(event){
 const link=event.target.closest('#main-tabs [data-tab]');if(!link)return;event.preventDefault();
 const tab=link.dataset.tab,remembered=navMemory[tab]||(tab==='library'?navFormat({tab:'library',library:libraryId||'all',view:'files'}):'#/'+tab);
 if(location.hash===remembered){navApply(navParse(remembered),{fromLink:false});return;}
 navInternal=true;location.hash=remembered;
}
let navInternal=false,navStarted=false;
// Routes name libraries, so start once the first state has loaded.
function navStateLoaded(){if(navStarted)return;navStarted=true;initNavigation();}
function navOnHashChange(){
 const route=navParse(location.hash),fromLink=!navInternal;navInternal=false;
 const previous=navCurrent?navFormat(navCurrent):null;
 if(!navApply(route,{fromLink})&&previous)history.replaceState(null,'',previous);
}
function initNavigation(){
 const tabs=$('main-tabs');if(!tabs)return;
 tabs.addEventListener('click',navTabClick);
 window.addEventListener('hashchange',navOnHashChange);
 const route=navParse(location.hash||'#/library');
 if(!location.hash)history.replaceState(null,'',navFormat(route.tab==='library'?{tab:'library',library:libraryId||'all',view:'files'}:route));
 navApply(route,{fromLink:Boolean(location.hash)});
}
