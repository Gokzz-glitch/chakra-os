(() => {
  const labels = {action:'Selected',progress:'Working',success:'Done',error:'Attention'};
  const pitches = {action:[430],progress:[330],success:[480,640],error:[340,245]};
  const patterns = {action:8,progress:12,success:[12,40,16],error:[22,45,22]};
  let sound=false, vibration=false, audio, timer, activated=false;
  try {const p=JSON.parse(localStorage.getItem('chakra_feedback')||'{}');sound=p.sound===true;vibration=p.vibration===true;}catch{}
  function unlock(){
    activated=true;
    if(sound){try{const Context=window.AudioContext||window.webkitAudioContext;if(Context){audio ||= new Context();audio.resume().catch(()=>{});}}catch{}}
  }
  document.addEventListener('pointerdown',unlock,true);document.addEventListener('keydown',unlock,true);
  function emit(kind,message){
    const out=document.getElementById('chakra-feedback-status');if(!out)return;
    out.dataset.kind=kind;out.textContent=labels[kind]+' · '+message;out.hidden=false;
    clearTimeout(timer);timer=setTimeout(()=>{out.hidden=true;},kind==='error'?8000:3300);
    if(!activated||document.hidden)return;
    if(vibration&&navigator.vibrate)navigator.vibrate(patterns[kind]);
    if(sound&&audio?.state==='running'){
      pitches[kind].forEach((hz,i)=>{
        const at=audio.currentTime+i*.10, tone=audio.createOscillator(),gain=audio.createGain();
        tone.frequency.value=hz;tone.connect(gain);gain.connect(audio.destination);
        gain.gain.setValueAtTime(.0001,at);gain.gain.exponentialRampToValueAtTime(.045,at+.012);
        gain.gain.exponentialRampToValueAtTime(.0001,at+.09);tone.start(at);tone.stop(at+.10);
        tone.onended=()=>{tone.disconnect();gain.disconnect()};
      });
    }
  }
  async function request(label,url,options){
    emit('progress',label);
    try{
      const response=await fetch(url,options);
      if(!response.ok)throw Error('HTTP '+response.status);
      const isJson=response.headers.get('content-type')?.includes('application/json');
      const data=isJson?await response.clone().json():null;
      if(data?.error||data?.status==='error'||data?.ok===false||data?.bigquery?.bq_errors?.length)throw Error('Operation reported an error');
      emit('success',label);return response;
    }catch(err){emit('error',label+' failed');throw err}
  }
  window.chakraFeedback={emit,request};
  document.addEventListener('DOMContentLoaded',()=>{
    const style=document.createElement('style');style.textContent=`
#chakra-feedback-settings{position:relative;display:inline-block;margin:4px;font:13px system-ui;color:var(--text,inherit);z-index:10}
#chakra-feedback-settings summary{cursor:pointer;padding:7px 12px;border:1px solid var(--line,#8793a2);border-radius:8px;list-style:none}
#chakra-feedback-settings .fb-options{position:absolute;right:0;top:100%;min-width:190px;padding:12px;border:1px solid #82909a;border-radius:8px;background:var(--panel,#fff);color:var(--text,#17202a)}
#chakra-feedback-settings label{display:flex;align-items:center;gap:8px;margin:4px;padding:4px;font:inherit;color:inherit}
#chakra-feedback-settings input{width:auto;margin:0}
#chakra-feedback-status{position:fixed;bottom:max(14px,env(safe-area-inset-bottom));left:50%;transform:translateX(-50%);max-width:90vw;width:max-content;padding:10px 16px;background:#202938;color:white;border-radius:10px;border-left:5px solid #a2c6ff;z-index:9999;font:14px/1.4 system-ui;pointer-events:none}
#chakra-feedback-status[data-kind=success]{border-color:#65d399}#chakra-feedback-status[data-kind=error]{border-color:#ff9a83}
`;document.head.append(style);
    const prefs=document.createElement('details');prefs.id='chakra-feedback-settings';
    prefs.innerHTML='<summary>Feedback</summary><div class="fb-options"><label><input type="checkbox" data-pref="sound"> Sound</label><label><input type="checkbox" data-pref="vibration"> Vibration</label></div>';
    const head=document.querySelector('header.top, header.hdr,.hdr');
    if(head)head.append(prefs);else document.body.prepend(prefs);
    const out=document.createElement('div');out.id='chakra-feedback-status';out.setAttribute('role','status');out.setAttribute('aria-live','polite');out.hidden=true;document.body.append(out);
    const [a,h]=prefs.querySelectorAll('input');a.checked=sound;h.checked=vibration&&!!navigator.vibrate;
    if(!navigator.vibrate){h.disabled=true;h.parentElement.append(' (unavailable)')}
    prefs.onchange=()=>{sound=a.checked;vibration=h.checked;try{localStorage.setItem('chakra_feedback',JSON.stringify({sound,vibration}))}catch{}unlock();emit('success','Feedback preferences saved')};
    document.addEventListener('click',e=>{
      if(!e.isTrusted||prefs.contains(e.target))return;
      const item=e.target.closest('button,a,summary,[role=button]');if(!item||item.disabled)return;
      const text=(item.getAttribute('aria-label')||item.textContent||'Control').trim().replace(/\s+/g,' ').slice(0,65);
      emit('action',text);
    },true);
    document.addEventListener('change',e=>{
      const el=e.target;if(prefs.contains(el))return;
      if(el.type==='range')emit('action','Confidence threshold '+Number(el.value).toFixed(2));
      else if(el.matches('select,input[type=checkbox],input[type=file],input[type=radio]'))emit('action',el.type==='file'?'File selected':'Selection changed');
    },true);
    const dialog=()=>document.querySelector('dialog[open]');
    const nativeAlert=window.alert;
    window.alert=message=>{emit('error','Action needs attention');return nativeAlert.call(window,message)};
    document.addEventListener('playing',e=>{if(e.target.matches('video,audio'))emit('success','Playback started')},true);
    document.addEventListener('error',e=>{if(e.target instanceof HTMLMediaElement)emit('error','Media could not play')},true);
    document.addEventListener('pause',e=>{if(e.target.matches('video,audio')&&e.target.currentTime>0&&!e.target.ended)emit('action','Playback paused')},true);
  });
})();
