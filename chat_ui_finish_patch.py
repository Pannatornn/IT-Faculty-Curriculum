from __future__ import annotations


FINAL_UI_PATCH = r'''<script>
// Final UX fixes: keep the chat viewport scrollable at 100% zoom and reduce
// oversized evidence rendering.
(()=>{
  const style=document.createElement('style');
  style.id='chatViewportFix';
  style.textContent=`
    html,body{height:100%;overflow:hidden!important}
    .shell{height:100vh!important;height:100dvh!important}
    .main{min-height:0!important;overflow:hidden!important}
    .thread{min-height:0!important;overflow-y:auto!important;overflow-x:hidden!important}
    .thread-inner{padding-bottom:var(--composer-space,180px)!important;max-width:820px!important}
    .msg,.bubble{max-width:100%!important;overflow-wrap:anywhere!important}
    .evidence{max-height:none!important;overflow:visible!important}
    .ev{font-size:12px!important}
  `;
  document.head.appendChild(style);

  // Keep Google OAuth deferred until provider setup is completed.
  const google=document.querySelector('#googleAuthBtn');
  const divider=document.querySelector('.auth-divider');
  if(!google) return;
  google.hidden=true;
  google.style.display='none';
  if(divider){divider.hidden=true;divider.style.display='none';}

  const cfg=window.CHAT_CONFIG||{};
  if(!cfg.supabaseUrl||!cfg.supabaseAnonKey) return;
  const settingsUrl=String(cfg.supabaseUrl).replace(/\/$/,'')+'/auth/v1/settings';
  fetch(settingsUrl,{headers:{apikey:cfg.supabaseAnonKey}})
    .then(r=>r.ok?r.json():null)
    .then(data=>{
      if(data?.external?.google===true){
        google.hidden=false;
        google.style.display='flex';
        if(divider){divider.hidden=false;divider.style.display='flex';}
      }
    }).catch(()=>{});
})();
</script>'''


def inject_final_ui_patch(html: str) -> str:
    return html.replace("</body>", FINAL_UI_PATCH + "\n</body>", 1)
