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
const navMemory={};let navApplying=false,navCurrent=null,navNotice='';

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
function navReviewCount(){return state.tasks.filter(t=>t.status==='awaiting_review'&&!t.deleted).length;}

// Apply a route to the existing workspaces. Returns false when the user kept unsaved work.
function navApply(route,{fromLink=true}={}){
 const leaving=(document.body.dataset.tab||'library')!==route.tab||route.tab==='library'||route.tab==='history';
 if(leaving&&inspectorDirty&&!prepareInspector())return false;
 navApplying=true;let notice=route.unknown?'That link is not available any more; showing the nearest view.':'';
 try{
  if(route.tab==='home'){if(openedTask)closeInspector(true);navSetTab('home');renderHome();navBanner('');}
  else if(route.tab==='configuration'){if(openedTask)closeInspector(true);navSetTab('configuration');renderConfiguration(route);navBanner('');}
  else if(route.tab==='history'){
   navSetTab('history');const q=route.query||{};
   if(q.library&&q.library!=='all'){if(navLibraryExists(q.library)){if(q.library!==libraryId&&!chooseLibrary(q.library))return false;historyScope='library';}else notice='That library is no longer connected; showing all libraries.';}
   if(q.library==='all'||notice)historyScope='all';
   historyView=['jobs','curator'].includes(q.view)?q.view:'jobs';historyPeriod=['all','1','7','30'].includes(q.period)?q.period:'all';historyStatus=q.status||'all';historyLevel=q.level||'all';
   if(!setScreen('history'))return false;
   const filtered=Object.keys(q).some(k=>k!=='library'&&q[k]&&q[k]!=='all');navBanner(fromLink&&filtered?'Opened from a link: History is filtered by the address. Filters only change what you see.':'',{tab:'history'});
  }else{
   navSetTab('library');const q=route.query||{};let id=route.library;
   if(id&&id!=='all'&&!navLibraryExists(id)){notice='That library is no longer connected; showing all libraries.';id='all';}
   const scoped=id&&id!=='all';
   if(scoped&&id!==libraryId&&!chooseLibrary(id))return false;
   const view=route.view||'files';
   if(view==='files'){
    if(!scoped&&!libraryId&&state.libraries.length&&!chooseLibrary(state.libraries[0].id))return false;
    libraryView=['attention','files','completed'].includes(q.view)?q.view:'attention';activeGrouping=['folder','task','movie'].includes(q.group)?q.group:'folder';
    if($('group-by'))$('group-by').value=activeGrouping;if(!setScreen('library'))return false;
    if(q.asset&&state.assets.some(a=>a.id===q.asset&&a.library===libraryId)){selectedAssetId=q.asset;render();}
    navBanner(fromLink&&(q.view||q.dimension||q.asset)?'Opened from a link: showing '+(NAV_VIEW_TEXT[libraryView]||'items')+(q.dimension?' for '+q.dimension:'')+'. Filters only change what you see.':'',{tab:'library',library:id||'all',view:'files'});
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
 const page=$('home-page');if(!page)return;
 const links=[['Library Manager','Browse and fix items in a library',navFormat({tab:'library',library:libraryId||'all',view:'files'})],['Ready to review',navReviewCount()+' waiting for your decision',navFormat({tab:'library',library:'all',view:'review'})],['Queue','Everything waiting or running, across all libraries',navFormat({tab:'library',library:'all',view:'queue'})],['History','What Curator and you have done',navFormat({tab:'history'})],['Configuration','Connections, processing defaults and standards',navFormat({tab:'configuration'})]];
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
