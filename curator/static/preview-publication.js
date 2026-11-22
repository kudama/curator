/* A trailer write always has its own exact destination review and approval. */
async function openPreviewPublication(identity,version,existing){
 if(!prepareInspector())return;const epoch=++previewView;openedTask=identity;inspectorMode='preview-publication';$('task-kind').textContent='PUBLISH TRAILER';$('task-title').textContent='Review local trailer';$('task-reason').hidden=true;const detail=$('task-detail'),actions=$('task-buttons');detail.replaceChildren(node('p','Checking candidate and destination…'));actions.replaceChildren();showPreviewInspector();
 const current=()=>openedTask===identity&&inspectorMode==='preview-publication'&&epoch===previewView;
 let plan=existing?await api('preview/publish?'+new URLSearchParams({id:existing})):await api('preview/publish/plan',{id:identity,version});if(!current())return;const requestId=clientId();
 function render(){if(!current())return;detail.replaceChildren(node('p',plan.title),node('p','Destination in Plex storage:'),node('code',plan.destination),node('p','Edition: '+(plan.edition||'Single movie file')),node('p','Candidate SHA256: '+plan.sha256),node('p','Existing trailers, original media and your Curator selection are retained. This adds a separate local trailer.'));
 for(const text of detail.querySelectorAll('p,code')){text.style.overflowWrap='anywhere';text.style.wordBreak='break-word';}
 for(const name of plan.prior_trailers||[])detail.append(node('p','Retained trailer: '+name,'muted'));
 const status=node('p',plan.status==='review'?'Review this exact destination before approving.':plan.status==='local_saved'?'Saved locally · Plex association '+plan.association:'File operation '+(plan.phase||plan.status));status.setAttribute('role','status');detail.append(status,node('p','Plex discovers local extras on its own schedule and may require a later metadata refresh. Curator does not force a refresh or change your agent.','muted'));if(plan.error)detail.append(node('p',plan.error,'error'));actions.replaceChildren();
 actions.append(button('Back to preview',()=>run(()=>openPreviewJob(identity)),'subtle'));
 if(plan.status==='review'){const approve=button('Approve & queue',()=>run(async()=>{approve.disabled=true;$('task-dialog').querySelector('[data-close]').disabled=true;try{plan=await api('preview/publish/approve',{plan:plan.id,request_id:requestId});if(!current())return;$('task-dialog').querySelector('[data-close]').disabled=false;closeInspector(true);await refresh();toast('Trailer queued in File operations.');}finally{if(current()){$('task-dialog').querySelector('[data-close]').disabled=false;approve.disabled=false;}}}),'primary preview-primary');actions.append(approve);}
 if(plan.status==='local_saved')actions.append(button('Check Plex association',()=>run(async()=>{plan=await api('preview/publish/check',{id:plan.id});render();}),'subtle'));
 if(plan.file_job)actions.append(button('File operations queue',()=>{closeInspector(true);queueStatus='all';setScreen('processing');},'text-button'));
 }
 render();
}
