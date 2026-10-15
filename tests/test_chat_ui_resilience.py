"""Exercise the shipped inline runtime with a minimal DOM and real promises.

These checks cover request/storage transitions; rendered browser QA complements
them for layout and accessibility.
"""
import re
import shutil
import subprocess

import pytest

from chat_ui import render_chat_ui
from chat_ui_finish_patch import inject_final_ui_patch
from chat_ui_patch import inject_chat_runtime_patch


DOM = r"""
const assert = require('node:assert/strict');
const crypto = require('node:crypto').webcrypto;
const elements = new Map();
function element(selector) {
  if (!elements.has(selector)) elements.set(selector, {
    value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,
    dataset:{},style:{},scrollHeight:50,scrollTop:0,
    classList:{add(){},remove(){},toggle(){}},
    querySelectorAll(){return []}, appendChild(){},
    insertAdjacentHTML(_where,html){this.innerHTML+=html},
    remove(){},focus(){},click(){},closest(){return null},
  });
  return elements.get(selector);
}
const document={querySelector:element,querySelectorAll(){return []},
  createElement(){return element('created-'+Math.random())},addEventListener(){}};
const window={CHAT_CONFIG:{}};
const location={origin:'https://curriculum.example'};
const memory=new Map();
const localStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)};
const sessionStorage={getItem(){return null},setItem(){},removeItem(){}};
const requestAnimationFrame=fn=>fn();
let requestHandler=async()=>({ok:true,json:async()=>({configured:false,authorized:false})});
const fetch=(url,options)=>requestHandler(url,options);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const alert=()=>{},confirm=()=>true,prompt=()=>null;
"""


def run_runtime(scenario: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for inline runtime checks")
    html = render_chat_ui({})
    runtime = next(s for s in re.findall(r"<script>(.*?)</script>", html, re.S)
                   if "window.CHAT_CONFIG=" in s)
    script = DOM + "\n" + runtime + "\n" + "(async()=>{await flush();\n" + scenario + "\n})().catch(e=>{console.error(e);process.exitCode=1});"
    result = subprocess.run([node, "-"], input=script, text=True,
                            encoding="utf-8", capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_double_submit_saves_one_user_turn_and_retry_does_not_duplicate_it():
    run_runtime(r"""
      let resolveChat,calls=0;
      requestHandler=async(url)=>{calls++;return new Promise(resolve=>resolveChat=resolve)};
      element('#composer').value='AIT credits?';
      const first=sendMessage();const ignored=sendMessage();
      await flush();assert.equal(calls,1);
      resolveChat({ok:false,status:503,json:async()=>({error:'Temporarily unavailable'})});
      await first;await ignored;
      assert.equal(messages.filter(m=>m.role==='user').length,1);
      assert.equal(currentConversation.messages.filter(m=>m.role==='user').length,1);
      const failed=messages.at(-1);assert.equal(failed.metadata.status,'ERROR');
      requestHandler=async()=>({ok:true,json:async()=>({answer:'120 credits',evidenceList:[]})});
      await sendMessage({question:failed.metadata.retryQuestion,history:failed.metadata.retryHistory});
      assert.equal(messages.filter(m=>m.role==='user').length,1);
      assert.equal(currentConversation.messages.filter(m=>m.role==='user').length,1);
      assert.equal(messages.at(-1).content,'120 credits');
      const old=currentConversation;await newChat();await openConversation(old.id);
      assert.notEqual(messages,old.messages);
    """)


def test_new_chat_aborts_request_and_ignores_its_late_response():
    run_runtime(r"""
      let resolveChat,signal;
      requestHandler=async(_url,opts)=>{signal=opts.signal;return new Promise(resolve=>resolveChat=resolve)};
      element('#composer').value='AIT credits?';const pending=sendMessage();await flush();
      const old=currentConversation;await newChat();assert.equal(signal.aborted,true);
      resolveChat({ok:true,json:async()=>({answer:'Late response'})});await pending;
      assert.equal(currentConversation,null);assert.equal(messages.length,0);
      assert.equal(old.messages.length,1);assert.equal(activeChat,null);
      assert.equal(element('#sendBtn').disabled,false);
    """)


def test_storage_failure_does_not_prevent_chat_and_sources_are_safe_and_collapsed():
    run_runtime(r"""
      localStorage.setItem=()=>{throw Error('quota exceeded')};
      requestHandler=async()=>({ok:true,json:async()=>({answer:'120 credits\nEVIDENCE:\nFACT-AIT-1 score=0.9'})});
      element('#composer').value='AIT credits?';await sendMessage();
      assert.equal(messages.at(-1).content,'120 credits');
      assert.match(element('#historyNote').textContent,/could not be saved/);
      const rendered=messageHtml({role:'assistant',content:'Answer\nEVIDENCE:\n[E1] ID=FACT-AIT-1\nSOURCE=secret technical block',metadata:{evidenceList:[{sourceDocTitle:'AIT',excerpt:'Relevant fact',sourceUrl:'javascript:alert(1)'},{sourceDocTitle:'IT',excerpt:'Second fact',sourceUrl:'https://example.org/doc.pdf#page=5'}]}});
      assert.match(rendered,/<details class="sources">/);assert.doesNotMatch(rendered,/<details[^>]*\bopen/);
      assert.doesNotMatch(rendered,/secret technical block|javascript:/);
      assert.match(rendered,/https:\/\/example.org\/doc.pdf#page=5/);
      assert.match(rendered,/\[E1\]/);assert.match(rendered,/\[E2\]/);
      assert.equal(sourceUrl(''),'');
      assert.equal(cleanAnswer('Answer\nEvidence supporting this conclusion is on page 5.'),'Answer\nEvidence supporting this conclusion is on page 5.');
      assert.equal(cleanAnswer('Answer\nEvidence:\nThe curriculum lists 120 credits [E1].'),'Answer\nEvidence:\nThe curriculum lists 120 credits [E1].');
      assert.equal(cleanAnswer('Answer\n[E1] ID=FACT-AIT-1\nSOURCE=AIT.pdf\nTEXT:\n120 credits'),'Answer');
    """)


def test_batch_pause_resume_keeps_completed_rows_and_retries_first_unfinished():
    run_runtime(r"""
      staffState={configured:true,authorized:true};imported=['First','Second'];
      let resolveSecond,calls=[];
      requestHandler=async(_url,opts)=>{const q=JSON.parse(opts.body).questions[0];calls.push(q);if(q==='First')return {ok:true,json:async()=>({rows:[{answer:'First answer',status:'OK'}]})};return new Promise(resolve=>resolveSecond=resolve)};
      const pending=runBatch();await flush();assert.equal(batchResults.filter(Boolean).length,1);
      stopBatch();assert.equal(element('#downloadBatch').disabled,false);
      resolveSecond({ok:true,json:async()=>({rows:[{answer:'Late second answer'}]})});await pending;
      assert.equal(batchResults.filter(Boolean).length,1);
      requestHandler=async(_url,opts)=>{calls.push(JSON.parse(opts.body).questions[0]);return {ok:true,json:async()=>({rows:[{answer:'Second answer',status:'OK'}]})}};
      await runBatch();assert.deepEqual(calls,['First','Second','Second']);
      assert.equal(batchResults.filter(Boolean).length,2);
      assert.equal(element('#runBatch').disabled,true);
      assert.equal(csvCell('=SUM(A1)'),"'=SUM(A1)");
    """)


def test_timeout_is_actionable_and_public_chat_does_not_send_a_stored_staff_key():
    run_runtime(r"""
      sessionStorage.getItem=()=> 'private-session-api-key';
      assert.equal(apiHeaders()['X-ThaiLLM-API-Key'],undefined);
      staffState={configured:true,authorized:true};
      assert.equal(apiHeaders()['X-ThaiLLM-API-Key'],'private-session-api-key');
      requestHandler=(_url,options)=>new Promise((_resolve,reject)=>{
        options.signal.addEventListener('abort',()=>{const e=Error('aborted');e.name='AbortError';reject(e)});
      });
      await assert.rejects(requestJson('/api/chat',{},new AbortController(),5),e=>e.name==='TimeoutError'&&/retry/.test(e.message));
    """)


def test_cloud_history_navigation_race_does_not_replace_new_chat():
    run_runtime(r"""
      let resolveHistory;
      const query={select(){return this},eq(){return this},order(){return new Promise(resolve=>resolveHistory=resolve)}};
      sb={from(){return query}};currentUser={id:'signed-in-user'};historyMode='cloud';
      conversations=[{id:'old-cloud-chat',title:'Old chat',user_id:currentUser.id}];
      const loading=openConversation('old-cloud-chat');assert.equal(historyLoading,true);
      await newChat();resolveHistory({data:[{role:'assistant',content:'Old response'}],error:null});await loading;
      assert.equal(messages.length,0);assert.equal(currentConversation,null);
      assert.equal(element('#conversationTitle').textContent,'New Chat');
      assert.equal(element('#sendBtn').disabled,false);
    """)


def test_hung_cloud_message_saves_release_chat_and_do_not_discard_or_duplicate_turns():
    run_runtime(r"""
      const realSetTimeout=setTimeout;
      global.setTimeout=(fn,delay,...args)=>realSetTimeout(fn,delay===CLOUD_WRITE_TIMEOUT_MS||delay===5000?5:delay,...args);
      const rows=[],pendingWrites=[];
      const makeQuery=()=>({select(){return this},eq(){return this},order(){return Promise.resolve({data:rows,error:null})},
        insert(row){this.row=row;rows.push(row);return this},single(){return new Promise(resolve=>pendingWrites.push(()=>resolve({data:this.row,error:null})))}});
      sb={from:makeQuery};currentUser={id:'cloud-user'};historyMode='cloud';
      currentConversation={id:'cloud-chat',user_id:currentUser.id,title:'AIT'};conversations=[currentConversation];
      requestHandler=async()=>({ok:true,json:async()=>({answer:'120 credits',evidenceList:[]})});
      element('#composer').value='AIT credits?';await sendMessage();
      assert.equal(activeChat,null);assert.equal(element('#sendBtn').disabled,false);
      assert.equal(messages.length,2);assert.equal(messages.at(-1).content,'120 credits');
      assert.equal(messages.filter(m=>m.role==='user').length,1);
      assert.ok(messages.every(m=>m.syncState==='unsynced'));
      assert.match(element('#historyNote').textContent,/could not sync/);
      pendingWrites.forEach(resolve=>resolve());await flush();assert.equal(messages.length,2);
      await openConversation('cloud-chat');assert.equal(messages.length,2);
      assert.equal(currentConversation.pendingMessages.length,0);
      assert.doesNotMatch(element('#historyNote').textContent,/could not sync/);
      global.setTimeout=realSetTimeout;
    """)


def test_stop_during_hung_cloud_user_save_records_one_stopped_turn_with_a_deadline():
    run_runtime(r"""
      const realSetTimeout=setTimeout;
      global.setTimeout=(fn,delay,...args)=>realSetTimeout(fn,delay===CLOUD_WRITE_TIMEOUT_MS||delay===5000?5:delay,...args);
      const query=()=>({insert(){return this},select(){return this},single(){return new Promise(()=>{})}});
      sb={from:query};currentUser={id:'cloud-user'};historyMode='cloud';
      currentConversation={id:'cloud-chat',user_id:currentUser.id,title:'AIT'};conversations=[currentConversation];
      let apiCalls=0;requestHandler=async()=>{apiCalls++;return {ok:true,json:async()=>({answer:'unused'})}};
      element('#composer').value='AIT credits?';const pending=sendMessage();await flush();
      const run=activeChat;assert.equal(messages.filter(m=>m.role==='user').length,1);
      cancelChat('stop');await Promise.all([pending,run.stopPromise]);
      assert.equal(apiCalls,0);assert.equal(activeChat,null);
      assert.equal(messages.filter(m=>m.role==='user').length,1);
      assert.equal(messages.filter(m=>m.metadata?.status==='STOPPED').length,1);
      assert.equal(element('#sendBtn').disabled,false);assert.equal(element('#composer').value,'');
      global.setTimeout=realSetTimeout;
    """)


def test_cloud_creation_and_timestamp_updates_have_bounded_failure_paths():
    run_runtime(r"""
      const realSetTimeout=setTimeout;
      global.setTimeout=(fn,delay,...args)=>realSetTimeout(fn,delay===CLOUD_WRITE_TIMEOUT_MS||delay===5000?5:delay,...args);
      currentUser={id:'cloud-user'};historyMode='cloud';
      sb={from(){return {insert(){return this},select(){return this},single(){return new Promise(()=>{})}}}};
      element('#composer').value='AIT credits?';await sendMessage();
      assert.equal(activeChat,null);assert.equal(element('#sendBtn').disabled,false);
      assert.equal(element('#composer').value,'AIT credits?');
      assert.match(messages.at(-1).content,/Creating the saved chat timed out/);
      currentConversation={id:'saved-chat',user_id:currentUser.id,title:'AIT'};conversations=[currentConversation];messages=[];
      sb={from(){return {insert(row){this.row=row;return this},select(){return this},single(){return Promise.resolve({data:this.row,error:null})},update(){return this},eq(){return new Promise(()=>{})}}}};
      const saved=await persistMessage('assistant','A saved answer',{},currentConversation);
      assert.equal(saved.syncState,'synced');assert.equal(messages.length,1);
      assert.match(element('#historyNote').textContent,/conversation order could not be refreshed/);
      global.setTimeout=realSetTimeout;
    """)


def test_overall_chat_deadline_releases_ui_before_hung_history_save_finishes():
    run_runtime(r"""
      const realSetTimeout=setTimeout;
      global.setTimeout=(fn,delay,...args)=>realSetTimeout(fn,delay===CHAT_TIMEOUT_MS?5:delay===CLOUD_WRITE_TIMEOUT_MS?50:delay,...args);
      sb={from(){return {insert(){return this},select(){return this},single(){return new Promise(()=>{})}}}};
      currentUser={id:'cloud-user'};historyMode='cloud';
      currentConversation={id:'cloud-chat',user_id:currentUser.id,title:'AIT'};conversations=[currentConversation];
      let calls=0;requestHandler=async()=>{calls++;return {ok:true,json:async()=>({answer:'unused'})}};
      element('#composer').value='AIT credits?';const pending=sendMessage();const run=activeChat;
      await new Promise(resolve=>realSetTimeout(resolve,15));
      assert.equal(activeChat,null);assert.equal(element('#sendBtn').disabled,false);
      assert.equal(messages.filter(m=>m.metadata?.status==='TIMEOUT').length,1);
      assert.equal(calls,0);await Promise.all([pending,run.stopPromise]);
      assert.equal(messages.filter(m=>m.role==='user').length,1);
      global.setTimeout=realSetTimeout;
    """)


def test_final_markup_has_no_nested_source_scroller_and_staff_token_is_not_stored():
    html = inject_final_ui_patch(inject_chat_runtime_patch(render_chat_ui({})))
    assert 'id="stopChat"' in html
    assert 'id="stopBatch"' in html
    assert "new AbortController()" in html
    assert "until you delete it or clear browser data" in html
    assert "max-height:260px" not in html
    assert "sourceUrl" in html
    assert "'/api/staff/session'" in html
    assert "body:JSON.stringify({token})" in html
    assert "setItem('staff" not in html
