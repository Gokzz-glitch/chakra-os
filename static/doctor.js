function openModal(id){ const el=document.getElementById(id); if(el) el.style.display='grid'; }
function closeModal(id){ const el=document.getElementById(id); if(el) el.style.display='none'; }

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
initTheme();

let code='', ws=null, timer=null, sec=0, lastReport=null;
const qp=new URLSearchParams(location.search);
if(qp.get('code')) codeIn.value=qp.get('code');
setInterval(()=>{ clock.textContent=new Date().toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata'})+' IST'; },1000);

async function connect(){
  code=codeIn.value.trim(); if(code.length!==6) return alert('Enter 6-digit code');
  const roomResponse=await fetch('/api/v2/rooms/'+code);
  if(!roomResponse.ok){
    startBtn.disabled=true;
    pId.textContent='Room unavailable · pair a current code';
    return;
  }
  const r=await roomResponse.json();
  pAnon.textContent=r.patient_anonymized_id; pId.textContent=r.procedure_id; pDoc.textContent=r.endoscopist_id;
  if(r.patient_consent && r.patient_consent.verified){
    pConsent.textContent=r.patient_consent.consent_id || 'DPDP Verified';
    pConsent.style.color='#059669';
  } else {
    pConsent.textContent='Awaiting Patient';
    pConsent.style.color='var(--warn)';
  }
  startBtn.disabled=false;
  if(ws) ws.close();
  const proto=location.protocol==='https:'?'wss:':'ws:';
  ws=new WebSocket(`${proto}//${location.host}/ws/v2/${code}/doctor`);
  ws.onmessage=e=>{
    const m=JSON.parse(e.data);
    if (m.type === 'ai_degraded') { hudImg.style.display='none'; hudStatus.textContent=m.message; feedBadge.textContent='AI unavailable'; tConf.textContent='—'; }
    if(m.type==='patient_consent_updated'){
      const c = m.patient_consent;
      pConsent.textContent = c.consent_id || 'DPDP Verified';
      pConsent.style.color = '#059669';
    }
    if(m.type==='phone_status'||m.type==='standby_heartbeat'){
      const on=m.connected||m.phone_connected;
      pPhone.textContent=on?'Paired & Ready':'Disconnected'; pPhone.style.color=on?'#059669':'#d97706';
    }
    if(m.type==='hud_frame'){
      hudImg.src='data:image/jpeg;base64,'+m.overlay_jpg_b64; hudImg.style.display='block'; standbyBox.style.display='none';
      pGpu.textContent=`${m.device} · ${m.latency_ms} ms`;
      feedBadge.textContent=`LIVE ${m.source.toUpperCase()} · ${m.latency_ms} ms`;
      hudStatus.textContent='LIVE AI OVERLAY ACTIVE';
      if(m.detections && m.detections.length){
        tConf.textContent=(Math.max(...m.detections.map(x=>x.conf))*100).toFixed(1)+'%';
      }
    }
    if(m.type==='findings_updated') renderFindings(m.findings);
    if(m.type==='voice_parsed'){
      const b=m.bbps_scores;
      bbpsTxt.textContent=`${b.right+b.transverse+b.left}/9 (${b.right}-${b.transverse}-${b.left})`;
      tLoc.textContent=m.suspected_location;
      voiceLog.textContent='Gemini parsed: '+m.parsed.clinical_note;
    }
  };
}
async function startProc(){
  await chakraFeedback.request('Start procedure',`/api/v2/rooms/${code}/doctor-start`,{method:'POST'});
  standbyBox.style.display='none'; endBtn.disabled=false;
  sec=0; if(timer) clearInterval(timer);
  timer=setInterval(()=>{
    sec++; const mm=String(Math.floor(sec/60)).padStart(2,'0'), ss=String(sec%60).padStart(2,'0');
    wTime.textContent=`${mm}:${ss}`; wTime.style.color=sec>=360?'#059669':'#d97706';
  },1000);
}
function renderFindings(list){
  const active=list.filter(f=>f.status!=='dismissed');
  lesionCnt.textContent=active.length;
  findingsList.replaceChildren(...list.map(f => {
    const row = uiNode('div', null, 'fnd');
    row.append(uiNode('span', f.id + ' · ' + (f.conf * 100).toFixed(0) + '% · ' + f.status),
      uiButton('Accept', () => rev(f.id, 'accepted')), uiButton('Dismiss', () => rev(f.id, 'dismissed')));
    return row;
  }));
}
async function rev(id,dec){
  await chakraFeedback.request('Save finding review',`/api/v2/rooms/${code}/finding-review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({finding_id:id,decision:dec})});
}
function toggleVoice(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR) { voiceLog.textContent='Speech recognition unavailable'; return; }
  const rec=new SR(); rec.lang='en-IN';
  micBtn.textContent='Listening...';
  rec.onresult=async e=>{ micBtn.textContent='Dictate Note'; await postVoice(e.results[0][0].transcript); };
  rec.onerror=()=>{ micBtn.textContent='Dictate Note'; voiceLog.textContent='Dictation failed. Please retry.'; };
  rec.start();
}
async function sendDemoVoice(){ await postVoice('BBPS right 3 transverse 3 left 2, 7mm sessile candidate in cecum, cold snare planned'); }
async function postVoice(text){
  voiceLog.textContent='Sending to Gemini 3.8 Flash...';
  await chakraFeedback.request('Save voice note',`/api/v2/rooms/${code}/voice-note`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({transcript:text})});
}
async function endAndReport(){
  const entry = {};
  for (const input of document.querySelectorAll('#measurements input')) {
    if (!input.reportValidity()) { repBody.textContent='Complete the clinical measurements.'; return; }
    entry[input.id.slice(8)] = input.valueAsNumber;
  }
  modalBg.style.display='grid'; hitlChk.checked=false; signBtn.disabled=true;
  lastReport=null;
  repBody.textContent='Preparing clinical report…';
  const measurementResponse = await fetch('/api/v2/rooms/'+code+'/measurements', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(entry)});
  if (!measurementResponse.ok) { repBody.textContent='Unable to save measurements.'; return; }
  const d=await (await chakraFeedback.request('Generate report',`/api/v2/rooms/${code}/end-report`,{method:'POST'})).json();
  if (!d.report) { repBody.textContent=d.detail || 'Report unavailable'; lastReport=null; return; }
  if(timer) clearInterval(timer);
  lastReport=d.report;
  const n=lastReport.narrative;
  repBody.replaceChildren(...[
    ['Status',lastReport.status], ['Pathology',lastReport.pathology_status], ['Consent', lastReport.patient_consent?.consent_id || 'Pending'],
    ['Surveillance (years)',lastReport.surveillance.years], ['Clinical summary',n.findings_summary],
    ['Discharge (English)',n.patient_discharge_english], ['Discharge (Tamil)',n.patient_discharge_tamil],
    ['Red flags',n.red_flag_precautions_english], ['Evidence',lastReport.evidence_gcs_uri || 'Pending capture']
  ].map(([label,value]) => uiNode('p', label + ': ' + value)));
  fhirBox.textContent=JSON.stringify(lastReport.abdm_fhir_r4,null,2);
}
async function playTts(lang){
  if(!lastReport) return;
  const txt=lang==='ta'?lastReport.narrative.patient_discharge_tamil:lastReport.narrative.patient_discharge_english;
  const d=await (await chakraFeedback.request('Prepare audio',`/api/v2/rooms/${code}/tts`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:txt})})).json();
  if(d.audio_b64){ ttsPlayer.src='data:audio/wav;base64,'+d.audio_b64; ttsPlayer.style.display='block'; ttsPlayer.play(); }
  else alert('TTS note: '+(d.error||'unavailable'));
}
async function commitBigQuery(){
  signBtn.textContent='Committing to BigQuery...';
  const d=await (await chakraFeedback.request('Sign off report',`/api/v2/rooms/${code}/signoff`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hitl_attested:true})})).json();
  if (!d.report || d.report.status !== 'FINAL') { signBtn.textContent='Retry sign-off'; repBody.textContent=d.detail || 'Sign-off failed'; return; }
  signBtn.textContent='Signed Off & Logged to BigQuery'; signBtn.disabled=true;
  fhirBox.textContent=JSON.stringify({status:d.report.status, bigquery:d.bigquery},null,2);
}
if(codeIn.value.length===6) connect();
