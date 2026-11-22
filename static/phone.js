// Prevent window.status collision in browser DOM
Object.defineProperty(window, 'status', {
  get() { return document.getElementById('status'); },
  set(v) {},
  configurable: true
});

function initTheme(){
  const saved=localStorage.getItem('chakra_theme')||'light';
  if(saved==='dark'){ document.documentElement.classList.add('dark'); updateThemeIcon(true); }
  else { document.documentElement.classList.remove('dark'); updateThemeIcon(false); }
}
function toggleTheme(){
  const isDark=document.documentElement.classList.toggle('dark');
  localStorage.setItem('chakra_theme',isDark?'dark':'light');
  updateThemeIcon(isDark);
}
function updateThemeIcon(isDark){
  const el=document.getElementById('themeIcon');
  const lbl=document.getElementById('themeLabel');
  if(el){
    el.textContent = isDark ? '☾' : '☀';
  }
  if(lbl) lbl.textContent=isDark?'Dark':'Light';
}
function openModal(id){ const el=document.getElementById(id); if(el) el.style.display='grid'; }
function closeModal(id){ const el=document.getElementById(id); if(el) el.style.display='none'; }
initTheme();

let ws=null, timer=null, sourceMode='live', sent=0;
const params=new URLSearchParams(location.search);
if(params.get('code')) codeIn.value=params.get('code');

async function checkConsentStatus(code){
  try {
    const res = await fetch(`/api/v2/rooms/${code}/patient-consent`);
    if(res.ok){
      const d = await res.json();
      updateConsentUi(d.patient_consent);
    }
  } catch(e){}
}

function updateConsentUi(c){
  if(c && c.verified){
    consentBadge.textContent = 'DPDP Verified · ' + (c.consent_id || 'DPDP-OK');
    consentBadge.style.background = '#d1fae5';
    consentBadge.style.color = '#065f46';
    chkAware.checked = true;
    chkDataSharing.checked = true;
    chkAware.disabled = true;
    chkDataSharing.disabled = true;
    btnVerifyConsent.disabled = true;
    btnVerifyConsent.textContent = 'Consent Verified & Active';
    consentMsg.textContent=`Verified under DPDP Act 2023 (${c.consent_id}). Zero-PHI streaming unlocked.`;
  }
}

async function submitPatientConsent(){
  const code = codeIn.value.trim();
  if(!code) return alert('Enter or pair a 6-digit room code first');
  if(!chkAware.checked || !chkDataSharing.checked){
    return alert('Please verify both Procedure Awareness and Data Sharing consent to proceed.');
  }
  consentMsg.textContent = 'Recording patient verification...';
  try {
    const res = await fetch(`/api/v2/rooms/${code}/patient-consent`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        aware_of_procedure: chkAware.checked,
        consent_data_sharing: chkDataSharing.checked,
        patient_signature: 'PATIENT_VERIFIED',
        language: 'en'
      })
    });
    const d = await res.json();
    if(res.ok){
      updateConsentUi(d.patient_consent);
      chakraFeedback.emit("success", "Patient consent verified");
    } else {
      consentMsg.textContent=`Error: ${d.detail}`;
    }
  } catch(e){
    consentMsg.textContent=`Failed to record verification: ${e}`;
  }
}

function pair(){
  const c=codeIn.value.trim(); if(c.length!==6) return alert('Enter the 6-digit code');
  if(ws) ws.close();
  const proto=location.protocol==='https:'?'wss:':'ws:';
  ws=new WebSocket(`${proto}//${location.host}/ws/v2/${c}/phone`);
  ws.onopen=()=>{ chakraFeedback.emit("success","Phone connected");
    const el=document.getElementById('status');
    if(el){ el.textContent='Paired to Room '+c+' · Ready to stream'; el.style.color='#059669'; }
    checkConsentStatus(c);
  };
  ws.onmessage=(e)=>{
    try {
      const m = JSON.parse(e.data);
      if(m.type==='patient_consent_updated') updateConsentUi(m.patient_consent);
    } catch(err){}
  };
  ws.onclose=()=>{ chakraFeedback.emit("error","Phone disconnected");
    const el=document.getElementById('status');
    if(el){ el.textContent='Disconnected from room'; el.style.color='#d97706'; }
  };
}
async function loadClips(){
  try{
    const d=await (await fetch('/api/v2/demo-videos')).json();
    cloudClipSel.replaceChildren(...clipOptions(d.videos));
  }catch(e){}
}
async function startCloudDemoVideo(){
  const opt=cloudClipSel.options[cloudClipSel.selectedIndex]; if(!opt) return;
  const name=opt.value, fmt=opt.getAttribute('data-fmt'), url=opt.getAttribute('data-url');
  sourceMode='cloud_demo:'+name;
  if(fmt==='avi'){
    txStat.textContent=`Streaming ${name} via OpenCV frame-extract fallback...`;
    vid.style.display='none';
    const img=new Image();
    img.crossOrigin='anonymous';
    img.src=`/api/v2/demo-videos/${name}/frame?idx=0`;
    img.onload=()=>{
      cvs.width=480; cvs.height=Math.round(480*(img.height/img.width||0.75));
      cvs.getContext('2d').drawImage(img,0,0,cvs.width,cvs.height);
      if(timer) clearInterval(timer);
      timer=setInterval(()=>{
        if(!ws||ws.readyState!==1) return;
        ws.send(JSON.stringify({type:'frame',source:sourceMode,image_b64:cvs.toDataURL('image/jpeg',0.6)}));
        sent++; txStat.textContent=`Streaming ${name} (OpenCV fallback) · Frames sent: ${sent}`;
      },260);
    };
  } else {
    vid.style.display='block';
    vid.srcObject=null; vid.src=url; await vid.play(); beginLoop();
  }
}
async function startCamera(){
  sourceMode='camera';
  try{
    const devices=await navigator.mediaDevices.enumerateDevices();
    const videoDevices=devices.filter(d=>d.kind==='videoinput'&&!d.label.toLowerCase().includes('obs virtual'));
    const deviceId=videoDevices.length?videoDevices[0].deviceId:undefined;
    const constraints={video:deviceId?{deviceId:{exact:deviceId},facingMode:'environment'}:{facingMode:'environment'},audio:false};
    const stream=await navigator.mediaDevices.getUserMedia(constraints);
    vid.style.display='block'; vid.srcObject=stream; await vid.play(); beginLoop();
  }catch(e){
    const stream=await navigator.mediaDevices.getUserMedia({video:true,audio:false});
    vid.style.display='block'; vid.srcObject=stream; await vid.play(); beginLoop();
  }
}
function startUploadedVideo(inp){
  const f=inp.files[0]; if(!f) return;
  sourceMode='simulated_live_video';
  vid.style.display='block'; vid.srcObject=null; vid.src=URL.createObjectURL(f); vid.play(); beginLoop();
}
function beginLoop(){
  if(timer) clearInterval(timer);
  timer=setInterval(()=>{
    if(!ws||ws.readyState!==1||!vid.videoWidth) return;
    const w=480, h=Math.round(480*(vid.videoHeight/vid.videoWidth));
    cvs.width=w; cvs.height=h;
    cvs.getContext('2d').drawImage(vid,0,0,w,h);
    ws.send(JSON.stringify({type:'frame',source:sourceMode,image_b64:cvs.toDataURL('image/jpeg',0.6)}));
    sent++; txStat.textContent=`Streaming ${sourceMode} · Frames sent: ${sent}`;
  },260);
}
loadClips();
if(codeIn.value.length===6) { pair(); checkConsentStatus(codeIn.value.trim()); }
