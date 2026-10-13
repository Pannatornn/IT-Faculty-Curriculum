from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

import render_server as core

PROCESS_CSS = r'''
.processing-overlay{position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;background:rgba(2,6,23,.68);backdrop-filter:blur(9px);-webkit-backdrop-filter:blur(9px)}
.processing-overlay.hidden{display:none}.processing-card{width:min(92vw,470px);border:1px solid rgba(99,102,241,.5);background:linear-gradient(180deg,rgba(15,23,42,.98),rgba(8,15,29,.98));border-radius:22px;padding:26px;box-shadow:0 24px 80px rgba(0,0,0,.45)}
.processing-top{display:flex;align-items:center;gap:16px}.processing-spinner{width:48px;height:48px;flex:0 0 48px;border-radius:50%;border:3px solid rgba(71,85,105,.65);border-top-color:#818cf8;border-right-color:#2dd4bf;animation:processingSpin .85s linear infinite}.processing-title{font-size:18px;font-weight:900;color:#f8fafc}.processing-sub{margin-top:5px;color:#94a3b8;font-size:12px;line-height:1.5}.processing-steps{margin-top:18px;display:grid;gap:8px}.processing-step{display:flex;align-items:center;gap:9px;padding:9px 11px;border:1px solid rgba(51,65,85,.62);border-radius:10px;background:rgba(15,23,42,.55);color:#64748b;font-size:11px;transition:.25s}.processing-step .dot{width:8px;height:8px;border-radius:50%;background:#475569;box-shadow:0 0 0 3px rgba(71,85,105,.12)}.processing-step.active{color:#e0e7ff;border-color:rgba(99,102,241,.58);background:rgba(79,70,229,.12)}.processing-step.active .dot{background:#818cf8;box-shadow:0 0 14px rgba(129,140,248,.85)}.processing-step.done{color:#86efac;border-color:rgba(34,197,94,.28)}.processing-step.done .dot{background:#22c55e}.processing-time{margin-top:13px;color:#64748b;font:700 10px ui-monospace,Consolas,monospace;text-align:right}
.competition-tools{max-width:850px;margin:14px auto 0;border:1px solid #33415588;background:#08101edb;border-radius:15px;padding:12px}.tool-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}.tool-title{font-size:12px;font-weight:900;color:#e2e8f0}.model-line{font:700 10px ui-monospace,Consolas,monospace;color:#5eead4}.tool-grid{display:grid;grid-template-columns:1.25fr 1fr;gap:10px}.tool-card{border:1px solid #33415588;background:#0f172a88;border-radius:12px;padding:12px}.tool-card h4{margin:0 0 5px;font-size:12px}.tool-card p{margin:0 0 9px;color:#94a3b8;font-size:10px;line-height:1.5}.tool-actions{display:flex;gap:7px;flex-wrap:wrap}.tool-btn{border:1px solid #47556999;background:#111c31;color:#dbeafe;border-radius:9px;padding:8px 10px;font-size:10px;font-weight:800;cursor:pointer}.tool-btn.primary{border:0;background:linear-gradient(90deg,#4f46e5,#14b8a6);color:#fff}.tool-btn:disabled{opacity:.45;cursor:not-allowed}.key-input{width:100%;border:1px solid #47556999!important;background:#02061799!important;color:#fff!important;border-radius:9px!important;padding:9px!important;margin-bottom:8px}.file-meta{margin-top:8px;color:#a5b4fc;font-size:10px}.batch-preview{margin-top:10px;display:none}.batch-preview.show{display:block}.batch-table-wrap{max-height:250px;overflow:auto;border:1px solid #33415588;border-radius:10px}.batch-table{width:100%;border-collapse:collapse}.batch-table th,.batch-table td{padding:7px 8px;border-bottom:1px solid #33415566;font-size:10px;text-align:left;vertical-align:top}.batch-table th{position:sticky;top:0;background:#111827;color:#c7d2fe}.batch-status{font:800 9px ui-monospace,Consolas,monospace}.batch-progress{height:7px;background:#1e293b;border-radius:999px;overflow:hidden;margin:9px 0}.batch-fill{height:100%;width:0;background:linear-gradient(90deg,#6366f1,#14b8a6);transition:width .25s}.batch-msg{font-size:10px;color:#94a3b8}.key-state{font-size:10px;margin-top:7px;color:#94a3b8}.key-state.ok{color:#86efac}.key-state.bad{color:#fda4af}
@keyframes processingSpin{to{transform:rotate(360deg)}}@media(max-width:850px){.tool-grid{grid-template-columns:1fr}.competition-tools{max-width:none}}
'''

PROCESS_HTML = r'''
<div id="processingOverlay" class="processing-overlay hidden" aria-live="polite" aria-busy="true"><div class="processing-card"><div class="processing-top"><div class="processing-spinner"></div><div><div id="processingTitle" class="processing-title">กำลังประมวลผล...</div><div id="processingSub" class="processing-sub">ระบบกำลังค้นหลักฐานและตรวจสอบคำตอบ กรุณารอสักครู่</div></div></div><div id="processingSteps" class="processing-steps"></div><div id="processingTime" class="processing-time">0s</div></div></div>
'''

PROCESS_JS = r'''
<script>
(()=>{
  if(window.__THAILLM_COMPETITION_PATCH__) return; window.__THAILLM_COMPETITION_PATCH__=true;
  const nativeFetch=window.fetch.bind(window); let timer=null,clock=null,started=0,currentStep=0,activeCount=0;
  const model='OpenThaiGPT-ThaiLLM-8B-Instruct-v7.2';
  const configs={
    '/api/ask':{th:['กำลังวิเคราะห์คำถาม...','ค้นหลักฐาน → ThaiLLM → ตรวจคำตอบ'],en:['Analyzing question...','Evidence retrieval → ThaiLLM → verification'],stepsTh:['ตรวจภาษาและขอบเขต','ค้นหา Evidence','ประมวลผลด้วย ThaiLLM','ตรวจสอบคำตอบ'],stepsEn:['Detect language & scope','Retrieve evidence','Process with ThaiLLM','Verify answer']},
    '/api/compare':{th:['กำลังเปรียบเทียบหลักสูตร...','รวบรวมหลักฐานจากทั้งสองหลักสูตร'],en:['Comparing programs...','Collecting balanced evidence from both curricula'],stepsTh:['วิเคราะห์โจทย์','รวบรวม Evidence','เปรียบเทียบ','ตรวจคำตอบ'],stepsEn:['Analyze focus','Collect evidence','Compare','Verify']},
    '/api/benchmark':{th:['กำลังรัน Judge Benchmark...','ประเมินชุด Easy baseline จริง'],en:['Running Judge Benchmark...','Evaluating the real Easy baseline'],stepsTh:['เตรียมโจทย์','รันทีละข้อ','ตรวจ Scope/Security','สรุป Metrics'],stepsEn:['Prepare cases','Run cases','Check scope/security','Aggregate metrics']},
    '/api/import-questions':{th:['กำลังอ่านไฟล์คำถาม...','ตรวจหา column question และรายการคำถาม'],en:['Reading question file...','Detecting the question column and rows'],stepsTh:['อ่านไฟล์','ตรวจ Header','ดึงคำถาม','เตรียม Batch'],stepsEn:['Read file','Detect header','Extract questions','Prepare batch']}
  };
  function endpointOf(input){try{const raw=typeof input==='string'?input:(input&&input.url)||'';return new URL(raw,location.origin).pathname}catch(_){return ''}}
  function uiEnglish(){return document.getElementById('en')?.classList.contains('on')}
  function renderSteps(items){const b=document.getElementById('processingSteps');if(b)b.innerHTML=items.map((s,i)=>`<div class="processing-step ${i===0?'active':''}"><span class="dot"></span><span>${s}</span></div>`).join('')}
  function markStep(i){[...document.querySelectorAll('.processing-step')].forEach((n,j)=>{n.classList.toggle('done',j<i);n.classList.toggle('active',j===i)})}
  function show(ep){const cfg=configs[ep],o=document.getElementById('processingOverlay');if(!cfg||!o)return;activeCount++;started=Date.now();currentStep=0;const en=uiEnglish();document.getElementById('processingTitle').textContent=(en?cfg.en:cfg.th)[0];document.getElementById('processingSub').textContent=(en?cfg.en:cfg.th)[1];renderSteps(en?cfg.stepsEn:cfg.stepsTh);o.classList.remove('hidden');clearInterval(timer);clearInterval(clock);timer=setInterval(()=>{const total=document.querySelectorAll('.processing-step').length;if(currentStep<total-1){currentStep++;markStep(currentStep)}},2200);clock=setInterval(()=>{const e=document.getElementById('processingTime');if(e)e.textContent=Math.floor((Date.now()-started)/1000)+'s'},500)}
  function hide(){activeCount=Math.max(0,activeCount-1);if(activeCount)return;clearInterval(timer);clearInterval(clock);[...document.querySelectorAll('.processing-step')].forEach(n=>{n.classList.remove('active');n.classList.add('done')});setTimeout(()=>document.getElementById('processingOverlay')?.classList.add('hidden'),150)}
  window.fetch=async function(input,init={}){const ep=endpointOf(input);const headers=new Headers(init.headers||{});const key=sessionStorage.getItem('thaillm_api_key')||'';if(key&&ep.startsWith('/api/'))headers.set('X-ThaiLLM-API-Key',key);const shouldShow=configs[ep]&&!window.__BATCH_RUNNING__;if(shouldShow)show(ep);try{return await nativeFetch(input,{...init,headers})}finally{if(shouldShow)hide()}};

  function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
  function bytesToBase64(buf){let binary='';const bytes=new Uint8Array(buf),chunk=0x8000;for(let i=0;i<bytes.length;i+=chunk)binary+=String.fromCharCode(...bytes.subarray(i,Math.min(i+chunk,bytes.length)));return btoa(binary)}
  function csvEscape(v){const s=String(v??'');return /[",\n\r]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s}
  let imported=[],results=[],importName='';

  function injectTools(){
    const chips=document.querySelector('#qa .chips'); if(!chips||document.getElementById('competitionTools'))return;
    const wrap=document.createElement('div');wrap.id='competitionTools';wrap.className='competition-tools';wrap.innerHTML=`
      <div class="tool-head"><div class="tool-title">⚙ Competition Tools — ใช้จากหน้าแรกได้ทั้งหมด</div><div class="model-line">${model}</div></div>
      <div class="tool-grid">
        <div class="tool-card"><h4>📄 Question Dataset (.xlsx / .csv)</h4><p>อัปไฟล์ Easy / Normal / Hard แล้วรันทุกคำถามผ่าน Universal Q&A เดียวกับช่องด้านบน จากนั้นดาวน์โหลด CSV รูปแบบ question,answer ได้ทันที</p><input id="questionFile" type="file" accept=".xlsx,.csv" hidden><div class="tool-actions"><button class="tool-btn" id="chooseFile">เลือกไฟล์</button><button class="tool-btn primary" id="runAll" disabled>▶ Run All Questions</button><button class="tool-btn" id="downloadCsv" disabled>⬇ Download answer.csv</button></div><div id="fileMeta" class="file-meta">ยังไม่ได้เลือกไฟล์</div><div id="batchPreview" class="batch-preview"><div class="batch-progress"><div id="batchFill" class="batch-fill"></div></div><div id="batchMsg" class="batch-msg"></div><div class="batch-table-wrap"><table class="batch-table"><thead><tr><th>#</th><th>Question</th><th>Status</th><th>Answer</th></tr></thead><tbody id="batchRows"></tbody></table></div></div></div>
        <div class="tool-card"><h4>🔑 ThaiLLM API Key</h4><p>เปลี่ยน key สำหรับ browser session นี้เท่านั้น ไม่เขียนลง GitHub/ไฟล์ หากไม่ใส่จะใช้ THAILLM_API_KEY จาก Environment ของระบบที่ Deploy</p><input id="keyInput" class="key-input" type="password" autocomplete="off" placeholder="Paste ThaiLLM API key"><div class="tool-actions"><button class="tool-btn primary" id="saveKey">Save Session Key</button><button class="tool-btn" id="clearKey">Use Deployment Key</button><button class="tool-btn" id="testKey">Test Connection</button></div><div id="keyState" class="key-state"></div></div>
      </div>`;
    chips.insertAdjacentElement('afterend',wrap);
    document.querySelector('.badge')?.replaceChildren(document.createTextNode('V2.2 COMPETITION'));
    const sub=document.getElementById('brandSub');if(sub)sub.textContent=model+' · Evidence-grounded IT KMITL Curriculum AI';

    const f=document.getElementById('questionFile');document.getElementById('chooseFile').onclick=()=>f.click();f.onchange=async()=>{const file=f.files?.[0];if(!file)return;imported=[];results=[];document.getElementById('runAll').disabled=true;document.getElementById('downloadCsv').disabled=true;try{const b64=bytesToBase64(await file.arrayBuffer());const r=await fetch('/api/import-questions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,contentBase64:b64})});const d=await r.json();if(!r.ok)throw Error(d.error||'Import failed');imported=d.questions||[];importName=d.filename||file.name;document.getElementById('fileMeta').textContent=`${importName} · ${imported.length} questions${d.sheet?' · sheet '+d.sheet:''}`;document.getElementById('runAll').disabled=!imported.length;renderBatchPreview()}catch(e){document.getElementById('fileMeta').textContent='Error: '+e.message}};

    document.getElementById('runAll').onclick=runAll;document.getElementById('downloadCsv').onclick=downloadCsv;
    const keyInput=document.getElementById('keyInput');if(sessionStorage.getItem('thaillm_api_key'))document.getElementById('keyState').textContent='Custom session key is active';
    document.getElementById('saveKey').onclick=()=>{const k=keyInput.value.trim();if(!k)return;sessionStorage.setItem('thaillm_api_key',k);keyInput.value='';const s=document.getElementById('keyState');s.className='key-state ok';s.textContent='Saved for this browser session only'};
    document.getElementById('clearKey').onclick=()=>{sessionStorage.removeItem('thaillm_api_key');keyInput.value='';const s=document.getElementById('keyState');s.className='key-state';s.textContent='Using deployment environment secret'};
    document.getElementById('testKey').onclick=async()=>{const s=document.getElementById('keyState');s.className='key-state';s.textContent='Testing...';try{const r=await fetch('/api/health');const d=await r.json();s.className='key-state '+(d.apiConnected?'ok':'bad');s.textContent=(d.apiConnected?'Connected · ':'Not connected · ')+(d.modelDisplay||model)+' · '+(d.customKey?'custom session key':'deployment key')}catch(e){s.className='key-state bad';s.textContent=e.message}};
  }

  function renderBatchPreview(){const box=document.getElementById('batchPreview');box.classList.add('show');const body=document.getElementById('batchRows');body.innerHTML=imported.map((q,i)=>`<tr data-i="${i}"><td>${i+1}</td><td>${esc(q)}</td><td class="batch-status">READY</td><td></td></tr>`).join('');document.getElementById('batchMsg').textContent=`Ready: ${imported.length} questions`;document.getElementById('batchFill').style.width='0%'}
  async function runAll(){if(!imported.length)return;window.__BATCH_RUNNING__=true;results=[];const run=document.getElementById('runAll');run.disabled=true;document.getElementById('downloadCsv').disabled=true;const rows=[...document.querySelectorAll('#batchRows tr')];try{for(let i=0;i<imported.length;i++){const q=imported[i],row=rows[i],st=row.children[2],ans=row.children[3];st.textContent='RUNNING';document.getElementById('batchMsg').textContent=`Processing ${i+1}/${imported.length}`;try{const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});const d=await r.json();if(!r.ok)throw Error(d.error||`HTTP ${r.status}`);results.push({question:q,answer:d.answer||d.answerTh||'',status:d.status||'',language:d.language||'',confidence:d.confidence??0});st.textContent=d.status||'DONE';ans.textContent=(d.answer||d.answerTh||'').slice(0,240)}catch(e){results.push({question:q,answer:'',status:'ERROR',language:'',confidence:0,error:e.message});st.textContent='ERROR';ans.textContent=e.message}document.getElementById('batchFill').style.width=Math.round((i+1)/imported.length*100)+'%'}document.getElementById('batchMsg').textContent=`Completed ${results.length}/${imported.length} · ready to download answer.csv`;document.getElementById('downloadCsv').disabled=false}finally{window.__BATCH_RUNNING__=false;run.disabled=false}}
  function downloadCsv(){if(!results.length)return;const lines=['question,answer',...results.map(r=>csvEscape(r.question)+','+csvEscape(r.answer))];const blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=(importName?importName.replace(/\.(xlsx|csv)$/i,'')+'_answer.csv':'answer.csv');document.body.appendChild(a);a.click();URL.revokeObjectURL(a.href);a.remove()}

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',injectTools);else injectTools();
})();
</script>
'''


def enhanced_ui() -> str:
    html = core.INDEX_HTML
    html = html.replace("V2.1.6 RENDER", "V2.2 COMPETITION")
    html = html.replace("</style>", PROCESS_CSS + "\n</style>", 1)
    html = html.replace("<body>", "<body>" + PROCESS_HTML, 1)
    html = html.replace("</body>", PROCESS_JS + "\n</body>", 1)
    return html


async def root(_: Request):
    return HTMLResponse(enhanced_ui(), headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0","X-Content-Type-Options":"nosniff"})


routes = [
    Route("/", root), Route("/favicon.ico", core.favicon), Route("/healthz", core.healthz),
    Route("/api/health", core.api_health), Route("/api/programs", core.api_programs),
    Route("/api/ask", core.api_ask, methods=["POST"]), Route("/api/compare", core.api_compare, methods=["POST"]),
    Route("/api/import-questions", core.api_import_questions, methods=["POST"]),
    Route("/api/run-batch", core.api_run_batch, methods=["POST"]),
    Route("/api/benchmark", core.api_benchmark, methods=["POST"]),
]
app = Starlette(routes=routes, debug=False)
