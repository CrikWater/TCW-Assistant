'use strict';
let token='', currentStatus=null, inFlight=false;
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
function note(text){$('notice').textContent=text;$('notice').hidden=!text;}
async function api(path,body,form=false){
 const options={headers:{}};
 if(body!==undefined){options.method='POST';options.headers['X-TCW-Token']=token;
  if(form)options.body=body;else{options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}}
 const r=await fetch(path,options);const d=await r.json();
 if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail||d));
 return d;
}
const fmt=(x,suffix='s')=>x===null||x===undefined?'Not measured':Number(x).toFixed(2)+suffix;
async function run(work){
 if(inFlight){note('Another local operation is in progress.');return;}
 inFlight=true;note('');$('working').hidden=false;
 document.querySelectorAll('button').forEach(b=>b.disabled=true);
 try{await work();}catch(e){note(e.message);}
 finally{inFlight=false;$('working').hidden=true;document.querySelectorAll('button').forEach(b=>b.disabled=false);await refreshStatus().catch(()=>{});}
}
function sources(items,label='Source evidence'){
 $('sources').replaceChildren();if(!items.length)return;
 $('sources').append(el('h2',label));
 for(const s of items){
  const card=el('article',undefined,'card source-card');
  card.append(el('h3',(s.source_id?'['+s.source_id+'] ':'')+s.title));
  card.append(el('p',[s.page_number?'PDF physical page '+s.page_number:'Section citation',s.section,'Version '+(s.version||'not stated')].join(' · '),'muted'));
  if(s.review_notes)card.append(el('p',s.review_notes,'muted'));
  card.append(el('blockquote',s.text));
  const a=el('a','Inspect evidence');a.href=s.preview_url;a.target='_blank';a.rel='noopener';
  const original=el('a','Open original file');original.href=s.original_url;
  card.append(a,original);
  if(s.source_path&&/^https:\/\//.test(s.source_path)){
   const remote=el('a','Original repository ↗');remote.href=s.source_path;remote.target='_blank';remote.rel='noopener noreferrer';card.append(remote);}
  card.append(el('p','Cosine similarity: '+Number(s.score).toFixed(4)+' · '+(s.authority||'Unspecified authority'),'muted'));
  $('sources').append(card);
 }
}
async function question(retrieveOnly=false){
 const text=$('question').value.trim();if(text.length<3){note('Enter a question first.');return;}
 await run(async()=>{
  $('answer-panel').hidden=true;$('sources').replaceChildren();$('diagnostic-panel').hidden=true;
  const r=await api(retrieveOnly?'/api/search':'/api/ask',{question:text,diagnostics:$('diagnostics').checked});
  if(retrieveOnly){sources(r.evidence,'Retrieved evidence');note('Retrieval only: no answer generation was requested. Scores are cosine similarity, not confidence.');
   if($('diagnostics').checked){$('diagnostic-panel').hidden=false;$('diagnostic-output').textContent=JSON.stringify(r,null,2);}return;}
  $('answer-panel').hidden=false;$('answer-text').textContent=r.answer;$('answer-status').textContent=r.status;
  $('answer-note').textContent=r.grounding_note;
  $('timing').replaceChildren(...[['Retrieval',r.metrics.retrieval_s],['First content token',r.metrics.time_to_first_content_token_s],['Total',r.metrics.total_s]].map(([k,v])=>el('span',k+': '+fmt(v))));
  $('timing').append(el('span','Generation: '+fmt(r.metrics.tokens_per_second,' tok/s')));
  sources(r.citations.length?r.citations:r.retrieved_evidence,r.citations.length?'Source evidence':'Retrieved context — not sufficient to support an answer');
  if(r.diagnostics){$('diagnostic-panel').hidden=false;$('diagnostic-output').textContent=JSON.stringify(r.diagnostics,null,2);}
 });
}
async function refreshStatus(){
 const s=await api('/api/status');currentStatus=s;
 $('ready').textContent=s.ready_for_query?'Services ready':'Setup / indexing required';$('ready').className='pill'+(s.ready_for_query?'':' warn');
 $('doc-count').textContent=s.document_count;$('chunk-count').textContent=s.chunk_count;
 $('system-json').textContent=JSON.stringify(s,null,2);
 $('model-choice').replaceChildren();
 for(const model of s.ollama.installed.filter(m=>!m.remote&&m.name!==s.embedding_model)){
  const opt=el('option',model.name);opt.value=model.name;opt.selected=model.name===s.generation_model;$('model-choice').append(opt);
 }
 if(!$('model-choice').options.length){const opt=el('option','No local models available');opt.value='';$('model-choice').append(opt);}
 $('system-cards').replaceChildren();
 const cards=[['Local inference',s.ollama.available?'Ollama available':'Ollama unavailable','Configured: '+s.generation_model+(s.missing_models.length?' · Missing: '+s.missing_models.join(', '):'')],
 ['Knowledge index',s.vector_db_available?'Qdrant available':'Unavailable',s.document_count+' documents · '+s.chunk_count+' chunks'],
 ['Memory',fmt(s.ram_used_gib,' GiB')+' / '+fmt(s.ram_total_gib,' GiB'),'Application: '+fmt(s.process_ram_mib,' MiB')],
 ['GPU telemetry',s.gpus.length?s.gpus.map(g=>g.name).join(', '):'Not available',s.gpus.length?s.gpus.map(g=>g.vram_used_mib+' / '+g.vram_total_mib+' MiB VRAM').join('; '):s.gpu_telemetry_note],
 ['Embeddings',s.embedding_model,'Generated on the configured local Ollama server'],
 ['Access boundary','Local workstation',s.authentication]];
 for(const [name,value,desc]of cards){const card=el('article',undefined,'card');card.append(el('h3',name),el('p',value,'system-value'),el('p',desc,'muted'));$('system-cards').append(card);}
 const rows=await api('/api/metrics');$('metrics').replaceChildren();
 if(!rows.length){$('metrics').append(el('p','No query measurements yet.','muted'));return;}
 const table=el('table'),head=el('tr');['Time','Model','Retrieval','First token','Total','Tokens/s'].forEach(x=>head.append(el('th',x)));table.append(head);
 for(const m of rows){const row=el('tr');[new Date(m.created_at).toLocaleString(),m.model||'No generation',fmt(m.retrieval_s),fmt(m.time_to_first_content_token_s),fmt(m.total_s),fmt(m.tokens_per_second,'')].forEach(x=>row.append(el('td',x)));table.append(row);}
 $('metrics').append(table);
}
async function loadKnowledge(){
 const [corpus,docs]=await Promise.all([api('/api/corpus'),api('/api/documents')]);
 const map=new Map(docs.map(d=>[d.document_id,d]));
 const records=[...corpus,...docs.filter(d=>!corpus.some(c=>c.document_id===d.document_id))];
 $('document-list').replaceChildren();$('excluded-list').replaceChildren();
 $('replace-select').replaceChildren(el('option','Create a new document'));$('replace-select').firstChild.value='';
 for(const r of records){
  if(r.status==='excluded'){$('excluded-list').append(el('p',r.title+' — '+r.review_notes,'muted'));continue;}
  const d=map.get(r.document_id);const card=el('article',undefined,'card');
  const top=el('div',undefined,'doc-head');top.append(el('h3',r.title),el('span',d?.active?'Indexed':r.status==='holdout'?'Demo holdout':'Not indexed','pill'));card.append(top);
  const meta=el('div',undefined,'doc-meta');
  meta.append(el('span',(r.department||'General')+' · '+(r.category||r.authority)),el('span','Version: '+(r.version||'Not stated')+' · '+(d?.chunk_count||0)+' chunks'));
  card.append(meta);if(r.review_notes)card.append(el('p',r.review_notes,'muted'));
  if(d)card.append(el('p','Indexed '+new Date(d.indexed_at).toLocaleString(),'muted'));
  const actions=el('div',undefined,'doc-actions');
  const button=(label,fn,cls='secondary')=>{const b=el('button',label,cls);b.onclick=()=>run(async()=>{const res=await fn();note(res.status+(res.chunk_count?' · '+res.chunk_count+' chunks':''));await loadKnowledge();});actions.append(b);};
  if(!d&&r.demo_eligible)button(r.status==='holdout'?'Index live-demo document':'Index document',()=>api('/api/corpus/'+r.document_id+'/import',{}));
  if(d){button(d.active?'Re-index':'Re-index and reactivate',()=>api('/api/documents/'+r.document_id+'/reindex',{}));
   if(d.active)button('Remove from active index',()=>api('/api/documents/'+r.document_id+'/deactivate',{}),'danger');
   const opt=el('option',d.title);opt.value=d.document_id;$('replace-select').append(opt);}
  const detail=el('details');detail.append(el('summary','Inspect metadata'));detail.append(el('pre',JSON.stringify(d||r,null,2)));
  card.append(actions,detail);$('document-list').append(card);
 }
}
document.querySelectorAll('.nav').forEach(b=>b.onclick=async()=>{
 document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!=='page-'+b.dataset.page);
 document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n===b));
 try{if(b.dataset.page==='knowledge')await loadKnowledge();if(b.dataset.page==='system')await refreshStatus();}catch(e){note(e.message);}
});
$('question-form').onsubmit=e=>{e.preventDefault();question();};
$('search-only').onclick=()=>question(true);
$('refresh').onclick=()=>run(refreshStatus);
$('model-form').onsubmit=e=>{e.preventDefault();run(async()=>{const r=await api('/api/generation-model',{name:$('model-choice').value});note('Selected local model: '+r.model);});};
$('index-startup').onclick=()=>run(async()=>{
 const corpus=await api('/api/corpus');const selected=corpus.filter(d=>d.status==='active'&&d.demo_eligible);
 for(let i=0;i<selected.length;i++){note('Indexing '+(i+1)+' of '+selected.length+': '+selected[i].title);await api('/api/corpus/'+selected[i].document_id+'/import',{});}
 note('Startup corpus indexing completed.');await loadKnowledge();
});
$('upload-form').onsubmit=e=>{e.preventDefault();run(async()=>{const r=await api('/api/upload',new FormData(e.target),true);note(r.status+' · '+(r.chunk_count||0)+' chunks');await loadKnowledge();});};
(async()=>{try{token=(await api('/api/session')).token;await refreshStatus();}catch(e){note('Application service unavailable: '+e.message);}})();
