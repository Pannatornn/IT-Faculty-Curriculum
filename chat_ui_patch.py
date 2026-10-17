from __future__ import annotations


ENGLISH_REPLACEMENTS = (
    ('<html lang="th">', '<html lang="en">'),
    ('＋ แชทใหม่', '＋ New chat'),
    ('ค้นหาแชท', 'Search chats'),
    ('⚙ เครื่องมือแข่งขัน', '⚙ Competition tools'),
    ('เข้าสู่ระบบเพื่อเก็บประวัติข้ามอุปกรณ์', 'Sign in to sync chat history across devices'),
    ('แชทใหม่', 'New Chat'),
    ('ถามภาษาไหน ตอบภาษานั้น · คำตอบอ้างอิงชุดข้อมูลหลักสูตร IT KMITL', 'Ask in any language — answers follow the question language · Evidence-grounded IT KMITL curriculum'),
    ('<h2>เข้าสู่ระบบ</h2>', '<h2>Sign in to IT KMITL Curricula</h2>'),
    ('ล็อกอินเพื่อเก็บบทสนทนาและเปิดดูย้อนหลังได้จากอุปกรณ์อื่น', 'Sign in to save conversations and access them from any device.'),
    ('>ปิด<', '>Close<'),
    ('<h2>เครื่องมือแข่งขัน</h2>', '<h2>Competition tools</h2>'),
    ('Batch question files และ API key สำหรับ browser session นี้', 'Batch question files and a session-only ThaiLLM API key.'),
    ('อัปโหลด .xlsx / .csv แล้วระบบจะรันทุกคำถามผ่าน pipeline เดียวกับหน้าแชท และดาวน์โหลด CSV แบบ question,answer', 'Upload .xlsx / .csv files, run every question through the same chat pipeline, and download a question,answer CSV.'),
    ('ยังไม่ได้เลือกไฟล์', 'No file selected'),
    ('ใช้ key นี้ใน session', 'Use this key for this session'),
    ('ใช้ Render key', 'Use deployment key'),
    ('เปลี่ยนชื่อ', 'Rename'),
    ('ลบแชท', 'Delete chat'),
    ("return'วันนี้'", "return'Today'"),
    ("return'เมื่อวาน'", "return'Yesterday'"),
    ("return'7 วันที่ผ่านมา'", "return'Previous 7 days'"),
    ("return'เก่ากว่านั้น'", "return'Older'"),
    ('ยังไม่มีบทสนทนา', 'No conversations yet'),
    ('มีอะไรให้ช่วยเรื่องหลักสูตร IT KMITL?', 'How can I help with IT KMITL curricula?'),
    ('ถามต่อเนื่อง เปรียบเทียบหลักสูตร หรืออัปโหลดชุดคำถามแข่งขันได้', 'Ask follow-up questions, compare programs, or upload competition question sets.'),
    ('AIT กับ DSBA ต่างกันอย่างไร?', 'How do AIT and DSBA differ for AI and data careers?'),
    ('หลักสูตร IT ปี 2565 มีความเชี่ยวชาญด้านใดบ้าง?', 'What specialization areas are in the IT 2565 curriculum?'),
    ('这四个专业的专业课程类学分从高到低如何排列?', 'Rank the specific-course credits across all four programs.'),
    ('IT International ใช้ภาษาอะไรในการเรียน?', 'What language is used in IT International?'),
    ('กำลังค้นหลักฐานและประมวลผล', 'Retrieving evidence and generating an answer'),
    ('ประวัติซิงก์กับบัญชีนี้', 'History synced to this account'),
    ('Supabase ยังไม่ได้ตั้งค่า', 'Cloud history is not configured'),
    ('ไม่สามารถสร้างคำตอบได้', 'Unable to generate a response'),
    ('เกิดข้อผิดพลาด: ', 'Error: '),
    ('ชื่อแชทใหม่', 'New chat title'),
    ('ลบแชทนี้?', 'Delete this chat?'),
    ('ยังไม่ได้ตั้งค่า SUPABASE_URL และ SUPABASE_ANON_KEY บน Render', 'SUPABASE_URL and SUPABASE_ANON_KEY are not configured on Render.'),
    ('กำลังเข้าสู่ระบบ...', 'Signing in...'),
    ('เข้าสู่ระบบสำเร็จ', 'Signed in successfully'),
    ('กำลังสร้างบัญชี...', 'Creating account...'),
    ('สร้างบัญชีแล้ว โปรดตรวจอีเมลหากระบบเปิด email confirmation', 'Account created. Check your email if email confirmation is enabled.'),
    ('ออกจากระบบ?', 'Sign out?'),
    ('ระบบไม่สามารถประมวลผลข้อนี้ได้: ', 'Unable to process this item: '),
    ('เสร็จ ${batchResults.length}/${imported.length}', 'Completed ${batchResults.length}/${imported.length}'),
    ('ใช้ custom key สำหรับ session นี้แล้ว', 'Custom key is active for this session'),
    ('กลับไปใช้ Render key แล้ว', 'Using the Render key'),
)


CHAT_THEME_CSS = r'''<style id="legacyChatTheme">
:root{
  --bg:#07101d;--side:#08101e;--panel:#0f172a;--panel2:#111c31;
  --text:#eef2ff;--muted:#94a3b8;--line:#334155;--accent:#6366f1;
  --teal:#14b8a6;--green:#22c55e;--danger:#fb7185;
}
html,body{background:#07101d!important;color:var(--text)!important}
body{background-image:radial-gradient(circle at 50% 0%,rgba(79,70,229,.16),transparent 35%),radial-gradient(circle at 85% 15%,rgba(20,184,166,.10),transparent 28%),linear-gradient(180deg,#07101d,#08111f 55%,#07101d)!important}
.sidebar{background:rgba(8,16,30,.97)!important;border-right:1px solid rgba(51,65,85,.76)!important;box-shadow:8px 0 30px rgba(2,6,23,.18)}
.brand{color:#f8fafc!important}.brand-mark{background:linear-gradient(135deg,#6366f1,#14b8a6)!important;color:white!important;box-shadow:0 0 22px rgba(99,102,241,.25)}
.brand-accent{color:#818cf8}.brand-teal{color:#5eead4}
.new-btn,.searchbox{border-color:rgba(71,85,105,.78)!important;background:rgba(15,23,42,.72)!important}.new-btn:hover,.tools-btn:hover,.user-btn:hover{background:rgba(49,46,129,.30)!important}.searchbox:focus{border-color:#6366f1!important;box-shadow:0 0 0 3px rgba(99,102,241,.12)}
.group-label{color:#64748b!important}.chat-row{color:#cbd5e1!important}.chat-row:hover,.chat-row.active{background:linear-gradient(90deg,rgba(79,70,229,.20),rgba(20,184,166,.07))!important}.chat-row.active{border:1px solid rgba(99,102,241,.30)}
.side-bottom{border-top-color:rgba(51,65,85,.65)!important}.user-btn,.tools-btn{color:#dbeafe!important}.avatar{background:#1e293b!important;color:#c7d2fe!important;border:1px solid rgba(99,102,241,.28)}
.main{background:transparent!important}.topbar{background:rgba(7,16,29,.76)!important;backdrop-filter:blur(14px);border-bottom:1px solid rgba(51,65,85,.62)!important}.top-title{color:#e0e7ff!important}.model{color:#5eead4!important;border:1px solid rgba(20,184,166,.25);background:rgba(15,118,110,.10);padding:5px 8px;border-radius:8px}
.welcome h1{font-size:30px!important;background:linear-gradient(90deg,#c7d2fe,#818cf8,#5eead4);-webkit-background-clip:text;color:transparent}.welcome p{color:#94a3b8!important}.suggest{border-color:rgba(71,85,105,.72)!important;background:rgba(15,23,42,.78)!important;color:#e2e8f0!important}.suggest:hover{background:rgba(49,46,129,.28)!important;border-color:rgba(99,102,241,.55)!important;transform:translateY(-1px)}
.msg.user .bubble{background:linear-gradient(135deg,rgba(49,46,129,.62),rgba(30,41,59,.90))!important;border:1px solid rgba(99,102,241,.42);box-shadow:0 8px 24px rgba(2,6,23,.16)}
.msg.assistant .avatar{background:linear-gradient(135deg,#4f46e5,#14b8a6)!important;color:white!important;border:0!important}.bubble{color:#e2e8f0!important}.tag{border-color:rgba(99,102,241,.38)!important;background:rgba(79,70,229,.10)!important;color:#c7d2fe!important}.ev{border-color:rgba(51,65,85,.78)!important;background:rgba(15,23,42,.82)!important;color:#cbd5e1!important}.ev b{color:#5eead4}.thinking{color:#94a3b8!important}.dots span{background:#818cf8!important}
.composer-wrap{background:linear-gradient(transparent,#07101d 30%)!important}.composer{background:rgba(8,16,30,.97)!important;border:1px solid rgba(99,102,241,.46)!important;box-shadow:0 18px 50px rgba(2,6,23,.42),0 0 0 1px rgba(20,184,166,.05)!important}.composer:focus-within{border-color:#818cf8!important;box-shadow:0 18px 50px rgba(2,6,23,.42),0 0 0 3px rgba(99,102,241,.10)!important}.composer textarea{color:#f8fafc!important}.composer textarea::placeholder{color:#64748b}.icon-btn{color:#cbd5e1!important}.icon-btn:hover{background:rgba(99,102,241,.16)!important}.send{background:linear-gradient(135deg,#6366f1,#14b8a6)!important;color:white!important;box-shadow:0 6px 18px rgba(79,70,229,.28)}.hint{color:#64748b!important}
.modal-backdrop{background:rgba(2,6,23,.78)!important;backdrop-filter:blur(9px)}.modal{background:linear-gradient(180deg,rgba(15,23,42,.99),rgba(8,15,29,.99))!important;border:1px solid rgba(99,102,241,.42)!important;box-shadow:0 30px 90px rgba(0,0,0,.48)!important}.modal h2{color:#f8fafc}.modal p,.auth-state{color:#94a3b8!important}.field{background:rgba(2,6,23,.55)!important;border-color:rgba(71,85,105,.84)!important;color:white!important}.field:focus{border-color:#6366f1!important;box-shadow:0 0 0 3px rgba(99,102,241,.10)}.primary{background:linear-gradient(90deg,#4f46e5,#14b8a6)!important}.secondary{background:#111c31!important;color:#dbeafe!important;border:1px solid rgba(71,85,105,.70)!important}.notice{background:rgba(15,23,42,.75)!important;border-color:rgba(71,85,105,.70)!important;color:#cbd5e1!important}.progress{background:#1e293b!important}.progress>div{background:linear-gradient(90deg,#6366f1,#14b8a6)!important}.batch-list{border-color:#334155!important}.batch-item{border-bottom-color:#334155!important}
.context{background:#0f172a!important;border-color:#475569!important;box-shadow:0 18px 45px rgba(2,6,23,.48)!important}.context button:hover{background:rgba(99,102,241,.14)!important}.context .del{color:#fda4af!important}
.google-auth{width:100%;display:flex;align-items:center;justify-content:center;gap:10px;margin-top:12px;padding:11px 14px;border-radius:10px;border:1px solid rgba(99,102,241,.38);background:rgba(15,23,42,.86);color:#f8fafc;font-weight:750;cursor:pointer}.google-auth:hover{border-color:#818cf8;background:rgba(49,46,129,.24)}.google-mark{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;background:white;color:#4285f4;font-weight:900;font-family:Arial,sans-serif}.auth-divider{display:flex;align-items:center;gap:10px;color:#64748b;font-size:10px;margin:14px 0 2px}.auth-divider:before,.auth-divider:after{content:"";height:1px;background:#334155;flex:1}
@media(max-width:760px){.topbar .model{display:none}.sidebar{background:#08101e!important}.welcome h1{font-size:26px!important}}
</style>'''


CHAT_RUNTIME_PATCH = r'''<script>
// Competition chat runtime patch: multi-turn context, English-first UI,
// Google OAuth entry point and IT KMITL Curricula visual identity.
(()=>{
  document.documentElement.lang='en';
  document.title='IT KMITL Curricula';

  const brand=document.querySelector('#appBrand');
  if(brand) brand.innerHTML='IT <span class="brand-accent">KMITL</span> <span class="brand-teal">Curricula</span>';

  const authModal=document.querySelector('#authModal .modal');
  if(authModal && !document.querySelector('#googleAuthBtn')){
    const intro=authModal.querySelector('p');
    const google=document.createElement('button');
    google.id='googleAuthBtn';
    google.type='button';
    google.className='google-auth';
    google.innerHTML='<span class="google-mark">G</span><span>Continue with Google</span>';
    intro?.insertAdjacentElement('afterend',google);
    google.insertAdjacentHTML('afterend','<div class="auth-divider">or continue with email</div>');
  }

  window.signInWithGoogle=async function(){
    const state=document.querySelector('#authState');
    if(!sb){if(state)state.textContent='Cloud authentication is not configured.';return;}
    if(state)state.textContent='Redirecting to Google...';
    try{
      const {error}=await withDeadline(sb.auth.signInWithOAuth({
        provider:'google',
        options:{redirectTo:window.location.origin+'/'},
      }),CLOUD_WRITE_TIMEOUT_MS,'Google sign-in');
      if(error && state)state.textContent=error.message;
    }catch(_){if(state)state.textContent='Google sign-in could not connect. Please retry.';}
  };
  document.querySelector('#googleAuthBtn')?.addEventListener('click',window.signInWithGoogle);

})();
</script>'''


def inject_chat_runtime_patch(html: str) -> str:
    for old, new in ENGLISH_REPLACEMENTS:
        html = html.replace(old, new)
    html = html.replace('</head>', CHAT_THEME_CSS + '\n</head>', 1)
    return html.replace('</body>', CHAT_RUNTIME_PATCH + '\n</body>', 1)
