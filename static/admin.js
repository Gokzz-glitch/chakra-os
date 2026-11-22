let roomCode=null, ws=null;

function openModal(id){ const el=document.getElementById(id); if(el) el.style.display='flex'; }
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
  if(lbl) lbl.textContent=isDark?'Dark Mode':'Light Mode';
}
initTheme();

function tab(id,el){
  document.querySelectorAll('section[id^=tab-]').forEach(s=>s.classList.add('hide'));
  document.getElementById('tab-'+id).classList.remove('hide');
  document.querySelectorAll('.nav').forEach(n=>n.classList.remove('active'));
  el.classList.add('active');
  if(id==='analytics') loadAnalytics();
  if(id==='history') loadPatientHistory('DEMO-PATIENT-01');
  if(id==='runs') loadRuns();
  if(id==='review') loadReviewTab();
}
async function loadPatientHistory(pId){
  histSecurityMsg.textContent = 'Loading patient history...';
  histSecurityMsg.style.color = 'var(--accent)';
  histContent.classList.remove('hide');
  encountersList.textContent='';
  try {
    const res = await fetch(`/api/v2/patients/${pId}/history`, {
      headers: {}
    });
    if(!res.ok){
      const err = await res.json();
      histSecurityMsg.textContent = `Error: ${err.detail}`;
      histSecurityMsg.style.color = '#dc2626';
      histContent.classList.add('hide');
      return;
    }
    const data = await res.json();
    histSecurityMsg.textContent = `Verified: Patient records secured within tenant boundary (${data.hospital_id})`;
    histSecurityMsg.style.color = 'var(--ok)';
    histContent.classList.remove('hide');
    histPatId.textContent = data.patient_id;
    histAbha.textContent = data.abha_id;
    histHospId.textContent = data.hospital_id;

    encountersList.replaceChildren(...data.encounters.map(enc => {
      const card = uiNode('section', null, 'card');
      card.append(uiNode('h3', enc.indication), uiNode('p', enc.date + ' · ' + enc.procedure_id),
        uiNode('p', 'Endoscopist: ' + enc.endoscopist_id + ' · BBPS: ' + (enc.bbps_scores?.total ?? 'Pending')),
        uiNode('p', enc.clinical_narrative), uiNode('h4', 'Findings and pathology'));
      for (const f of enc.findings) {
        const photo = uiNode('img');
        if (f.evidence_frame_url?.startsWith('/api/v2/demo-videos/')) photo.src = f.evidence_frame_url;
        photo.alt = 'Evidence frame'; photo.width = 100;
        card.append(photo, uiNode('p', [f.finding_id, f.location, f.size_mm + ' mm', f.morphology,
          f.physician_decision, f.pathology_status].join(' · ')),
          uiNode('p', f.pathology_result?.diagnosis || 'Pathology pending'),
          uiNode('p', f.surveillance_recommendation));
        for (const entry of f.pathology_addenda || []) card.append(uiNode('p', 'Addendum: ' + entry.diagnosis));
      }
      return card;
    }));
  } catch(e) {
    histSecurityMsg.textContent = 'Network or system error: ' + e;
    histSecurityMsg.style.color = '#dc2626';
  }
}
async function testCrossHospitalSecurity(){
  histPatientInput.value = 'PATIENT-MUMBAI-99';
  await loadPatientHistory('PATIENT-MUMBAI-99');
}
async function simulatePathologyArrival(){
  const fId = pathFindingSelect.value;
  pathReconcileResult.textContent = 'Transmitting signed pathology report...';
  try {
    const res = await chakraFeedback.request('Save pathology entry',`/api/v2/findings/${fId}/pathology`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        signed_by: 'DR-PATH-RAMESH-V',
        diagnosis: fId === 'FND-2025-01' ? 'Tubular Adenoma with Low-Grade Dysplasia' : 'Serrated Polyp with No Dysplasia',
        dysplasia_grade: fId === 'FND-2025-01' ? 'Low-Grade' : 'None',
        margins: 'Negative / Clear (R0 Resection)',
        icd_o_code: '8213/0'
      })
    });
    const d = await res.json();
    if(res.ok){
      pathReconcileResult.textContent=`Reconciled finding ${fId} with signed pathology. Preserved earlier decision: ${d.earlier_decision_preserved}. Surveillance updated to: ${d.finding.surveillance_recommendation}`;
      await loadPatientHistory('DEMO-PATIENT-01');
    } else {
      pathReconcileResult.textContent=`Error: ${d.detail}`;
    }
  } catch(e) {
    pathReconcileResult.textContent=`Error: ${e}`;
  }
}
async function warmup(){
  const d=await (await fetch('/api/warmup')).json();
  const ok=d.status==='ready';
  gpuDot.className='dot'+(ok?' ok':'');
  gpuTxt.textContent=ok?`L4 Ready: ${d.gpu}`:`Vision: ${d.status}`;
  wL4State.textContent=ok?`Online (${d.gpu})`:'Warming on demand';
}
async function loadCatalog(){
  const d=await (await fetch('/api/v2/catalog')).json();
  modelGrid.replaceChildren(...d.models.map(m => {
    const card = uiNode('div', null, 'card');
    card.append(uiNode('strong', m.name), uiNode('p', m.status), uiNode('p', m.type + ' · ' + m.id));
    return card;
  }));
}
async function mintRoom(){
  const r=await (await chakraFeedback.request('Create pairing room','/api/v2/rooms',{method:'POST'})).json();
  roomCode=r.code;
  codeBox.textContent=roomCode;
  procId.textContent=r.procedure_id;
  consentStatus.textContent = (r.patient_consent && r.patient_consent.verified) ? (r.patient_consent.consent_id || 'DPDP Verified') : 'Awaiting Patient';
  consentStatus.style.color = (r.patient_consent && r.patient_consent.verified) ? '#059669' : 'var(--warn)';
  docLink.href='/v2/doctor?code='+roomCode;
  phoneLink.href='/v2/phone?code='+roomCode;
  renderQr(roomCode);
  connectWs();
}
function renderQr(code){
  if(!code) return;
  const url=`${window.location.origin}/v2/phone?code=${code}`;
  qrRoomCode.textContent=code;
  qrUrlLabel.textContent=url;
  const inlineBox=document.getElementById('qrInline');
  if(inlineBox){
    inlineBox.textContent='';
    if(window.QRCode){ new QRCode(inlineBox,{text:url,width:72,height:72,correctLevel:QRCode.CorrectLevel.M}); }
    else { inlineBox.textContent = 'QR unavailable'; }
  }
  const modalBox=document.getElementById('qrModalBox');
  if(modalBox){
    modalBox.textContent='';
    if(window.QRCode){ new QRCode(modalBox,{text:url,width:220,height:220,correctLevel:QRCode.CorrectLevel.M}); }
    else { modalBox.textContent = 'QR unavailable'; }
  }
}
function openQrModal(){ qrModal.style.display='flex'; }
function closeQrModal(){ qrModal.style.display='none'; }

function connectWs(){
  if(ws) ws.close();
  const proto=location.protocol==='https:'?'wss:':'ws:';
  ws=new WebSocket(`${proto}//${location.host}/ws/v2/${roomCode}/admin`);
  ws.onmessage=e=>{
    const m=JSON.parse(e.data);
    if(m.type==='patient_consent_updated'){
      consentStatus.textContent = m.patient_consent.consent_id || 'DPDP Verified';
      consentStatus.style.color = '#059669';
    }
    if(m.type==='phone_status'){
      phoneDot.className='dot'+(m.connected?' ok':'');
      phoneTxt.textContent=m.connected?'Phone: Paired Live':'Phone: Waiting';
      phoneState.textContent=m.connected?'Connected (Streaming)':'Disconnected';
    }
    if(m.type==='procedure_started'){ docState.textContent='ACTIVE (Live Overlay On)'; docState.style.color='#10b981'; }
    if(m.type==='procedure_ended'){ docState.textContent='Completed (Report Modal)'; docState.style.color='#0b57d0'; }
    if(m.type==='frame_status'){ frameCnt.textContent=`${m.frames_processed} (${m.latency_ms} ms)`; }
  };
}
async function applyConfig(){
  if(!roomCode) return;
  await chakraFeedback.request('Apply configuration',`/api/v2/rooms/${roomCode}/config`,{
    method:'PATCH',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model:modelSel.value,conf:parseFloat(confRange.value),worker:workerSel.value,endoscopist_id:docId.value})
  });
  cfgMsg.textContent=`Synced ${modelSel.value} @ ${confRange.value} (${workerSel.value}) to Doctor HUD & Phone.`;
}
async function copyCode(){ if(!roomCode)return;try{await navigator.clipboard.writeText(roomCode);chakraFeedback.emit("success","Pairing code copied")}catch{chakraFeedback.emit("error","Could not copy pairing code")} }
async function runAdminTest(){
  const f=testFile.files[0]; if(!f||!roomCode) return alert('Choose an image or video file first');
  testMeta.textContent='Running Cloud Run L4 inference...';
  let blob=f;
  if(f.type.startsWith('video/')){
    const v=tmpVid; v.src=URL.createObjectURL(f);
    await new Promise(res=>{v.onloadeddata=()=>{v.currentTime=Math.min(1,v.duration/2||0);}; v.onseeked=res;});
    const c=document.createElement('canvas'); c.width=640; c.height=Math.round(640*(v.videoHeight/v.videoWidth||0.75));
    c.getContext('2d').drawImage(v,0,0,c.width,c.height);
    blob=await new Promise(res=>c.toBlob(res,'image/jpeg',0.85));
  }
  const fd=new FormData(); fd.append('file',blob,f.name||'test.jpg');
  const d=await (await chakraFeedback.request('Run frame test',`/api/v2/rooms/${roomCode}/admin-test-frame`,{method:'POST',body:fd})).json();
  testMeta.textContent=`${d.device} | ${d.latency_ms} ms | Detections: ${d.count}`;
  testImg.src='data:image/jpeg;base64,'+d.overlay_jpg_b64; testImg.classList.remove('hide');
}
async function loadAnalytics(){
  bqWrap.textContent='';
  const d=await (await fetch('/api/v2/analytics')).json();
  if(!d.metrics||!d.metrics.length){ bqWrap.textContent='No signed-off procedures in BigQuery yet. Complete a Doctor HUD sign-off to populate live metrics.'; return; }
  bqWrap.replaceChildren(...d.metrics.map(r => {
    const card = uiNode('div', null, 'card');
    card.append(uiNode('h3', r.endoscopist_id));
    for (const [label, value] of Object.entries({'Signed procedures': r.total_procedures,
      'Mean withdrawal (min)': r.mean_withdrawal_min, 'Mean GPU latency (ms)': r.mean_gpu_ms,
      'PDR (%)': r.pdr_pct, 'Adequate preparation (%)': r.prep_adequacy_pct})) card.append(uiNode('p', label + ': ' + value));
    return card;
  }));
}
async function loadClips(){
  try{
    const d=await (await fetch('/api/v2/demo-videos')).json();
    cloudClipSel.replaceChildren(...clipOptions(d.videos));
  }catch(e){}
}
async function runCloudClipTest(){
  if(!roomCode) return alert('Mint a room first');
  const opt=cloudClipSel.options[cloudClipSel.selectedIndex]; if(!opt) return;
  const name=opt.value, fmt=opt.getAttribute('data-fmt'), url=opt.getAttribute('data-url');
  testMeta.textContent=`Fetching frame from ${name}...`;
  let blob;
  if(fmt==='avi'){
    const r=await fetch(`/api/v2/demo-videos/${name}/frame?idx=0`);
    blob=await r.blob();
  } else {
    const v=tmpVid; v.src=url;
    await new Promise(res=>{v.onloadeddata=()=>{v.currentTime=Math.min(1,v.duration/2||0);}; v.onseeked=res;});
    const c=document.createElement('canvas'); c.width=640; c.height=Math.round(640*(v.videoHeight/v.videoWidth||0.75));
    c.getContext('2d').drawImage(v,0,0,c.width,c.height);
    blob=await new Promise(res=>c.toBlob(res,'image/jpeg',0.85));
  }
  testMeta.textContent='Running Cloud Run L4 inference on demo clip...';
  const fd=new FormData(); fd.append('file',blob,name);
  const d=await (await chakraFeedback.request('Run frame test',`/api/v2/rooms/${roomCode}/admin-test-frame`,{method:'POST',body:fd})).json();
  testMeta.textContent=`${d.device} | ${d.latency_ms} ms | Detections: ${d.count}`;
  testImg.src='data:image/jpeg;base64,'+d.overlay_jpg_b64; testImg.classList.remove('hide');
}

let allRuns=[];
let selectedRunId=null;

async function loadRuns(){
  try{
    const res=await fetch('/api/v2/runs');
    const data=await res.json();
    allRuns=Array.isArray(data)?data:(data.runs||[]);
    if(document.getElementById('runCountBadge')) runCountBadge.textContent=`${allRuns.length} Runs`;
    filterRunsTable();
  }catch(e){
    if(document.getElementById('runsTableBody')) runsTableBody.textContent=`Failed to load runs: ${e}`;
  }
}

function filterRunsTable(){
  if(!document.getElementById('runSearchInput')) return;
  const q=(runSearchInput.value||'').toLowerCase().trim();
  const st=runStatusFilter.value;

  const filtered=allRuns.filter(r=>{
    const matchesQ=!q||
      (r.run_id&&r.run_id.toLowerCase().includes(q))||
      (r.input_clip&&r.input_clip.toLowerCase().includes(q))||
      (r.model&&r.model.toLowerCase().includes(q))||
      (r.execution_worker&&r.execution_worker.toLowerCase().includes(q))||
      (r.review_status&&r.review_status.toLowerCase().includes(q));
    const matchesSt=st==='all'||r.review_status===st;
    return matchesQ&&matchesSt;
  });

  renderRunsTable(filtered);
}

function renderRunsTable(runs){
  if(!document.getElementById('runsTableBody')) return;
  if(!runs.length){
    runsTableBody.textContent=`No backend runs match filter.`;
    return;
  }

  runsTableBody.replaceChildren(...runs.map(r => {
    const row = uiNode('tr');
    for (const value of [r.run_id, r.timestamp ? new Date(r.timestamp).toLocaleString() : '—',
         r.input_clip || 'Live feed', r.model, (r.frames_total ?? '—') + ' (' + (r.frames_flagged ?? '—') + ')',
         r.fps, r.execution_worker, r.review_status || 'Pending']) row.append(uiNode('td', value));
    const actions = uiNode('td');
    actions.append(uiButton('Review', () => openInReview(r.run_id)));
    row.append(actions);
    return row;
  }));
}

function switchToReviewTab(){
  const navBtns=document.querySelectorAll('.nav');
  tab('review',navBtns[6]);
}

function openInReview(runId){
  selectedRunId=runId;
  switchToReviewTab();
  if(document.getElementById('reviewRunSel')) reviewRunSel.value=runId;
  displayRunInReview(runId);
}

async function loadReviewTab(){
  try{
    const res=await fetch('/api/v2/runs');
    const data=await res.json();
    allRuns=Array.isArray(data)?data:(data.runs||[]);

    if(document.getElementById('reviewRunSel')){
      reviewRunSel.replaceChildren(...allRuns.map(r => uiOption(r.run_id,
        '[' + (r.review_status || 'pending') + '] ' + r.run_id + ' · ' + (r.input_clip || 'Clip') + ' (' + r.model + ')')));

      const targetId=selectedRunId||(allRuns[0]?allRuns[0].run_id:null);
      if(targetId){
        reviewRunSel.value=targetId;
        displayRunInReview(targetId);
      }
    }
  }catch(e){
    console.error('Failed to load review tab runs:',e);
  }
}

function onReviewRunSelect(){
  if(!reviewRunSel) return;
  selectedRunId=reviewRunSel.value;
  displayRunInReview(selectedRunId);
}

function displayRunInReview(runId){
  selectedRunId=runId;
  const run=allRuns.find(r=>r.run_id===runId);
  if(!run) return;

  if(document.getElementById('sumRunId')) sumRunId.textContent=run.run_id;
  if(document.getElementById('sumTs')) sumTs.textContent=run.timestamp?(new Date(run.timestamp).toLocaleString()):'--';
  if(document.getElementById('sumHosp')) sumHosp.textContent=run.hospital_id||'—';
  if(document.getElementById('sumModel')) sumModel.textContent=run.model;
  if(document.getElementById('sumThresh')) sumThresh.textContent=run.threshold!=null?Number(run.threshold).toFixed(2):'0.45';
  if(document.getElementById('sumFrames')) sumFrames.textContent=`${run.frames_total||1} frames / ${run.frames_flagged||0} flagged`;
  if(document.getElementById('sumFps')) sumFps.textContent=run.fps?`${Number(run.fps).toFixed(1)} FPS`:'--';
  if(document.getElementById('sumWorker')) sumWorker.textContent=run.execution_worker||'Cloud Run NVIDIA L4';

  if(document.getElementById('sumFlStatus')){
    if(run.fl_eligible||run.review_status==='accepted'){
      sumFlStatus.textContent='FL-ELIGIBLE';
    }else if(run.review_status==='dismissed'){
      sumFlStatus.textContent='DISMISSED';
    }else{
      sumFlStatus.textContent='AWAITING REVIEW';
    }
  }

  if(document.getElementById('reviewReason')) reviewReason.value=run.clinician_notes||'';
  if(document.getElementById('reviewFeedback')) reviewFeedback.textContent='';

  const clip=run.input_clip||'';
  reviewVideo.onerror=null; reviewVideo.pause(); reviewVideo.removeAttribute('src'); reviewVideo.load();
  reviewImg.onerror=null; reviewImg.removeAttribute('src');
  for(const panel of [reviewVideoWrap,reviewImgWrap,reviewNoMedia,evidenceGalleryWrap])panel.classList.add('hide');
  previewBadge.textContent=clip||run.run_id;

  function notice(message){
    reviewVideoWrap.classList.add('hide');reviewImgWrap.classList.add('hide');
    reviewNoMedia.classList.remove('hide');reviewNoMedia.textContent=message+' ';
    const button=document.createElement('button');button.className='btn ghost';button.textContent='Browse saved evaluation replays';
    button.addEventListener('click',()=>document.getElementById('galaxyNav').click());
    reviewNoMedia.append(button);
  }
  const procedure=clip.startsWith('procedure_') && !!run.procedure_id;
  const first=run.flagged_evidence?.find(e=>e.evidence_url);
  const source=procedure ? (run.gcs_evidence_uris?.[0] || (run.media_url?.startsWith('data:image/') ? run.media_url : null))
                         : (run.media_url || first?.evidence_url);
  const shortClip=['/api/v2/demo-videos/ldpolyp_clip01.mp4','/api/v2/demo-videos/sun_seg_seq01.mp4'].includes(source);
  previewTitle.textContent=procedure?'Procedure evidence':'Run evidence';
  if(!source){
    notice(procedure?'No recording or evidence frame was saved for this procedure.':'No media was attached to this run.');
  }else if(source.startsWith('gs://girpolypposframesrealcolon-chakra-models/')){
    reviewNoMedia.textContent='This run has a private evidence file. ';
    const a=document.createElement('a');a.textContent='Open saved evidence';a.target='_blank';a.rel='noopener';
    const url='https://storage.cloud.google.com/'+source.slice(5).split('/').map(encodeURIComponent).join('/');
    a.href='https://accounts.google.com/AccountChooser?continue='+encodeURIComponent(url);
    reviewNoMedia.append(a);reviewNoMedia.classList.remove('hide');
  }else if(source.startsWith('data:image/') || source.startsWith('/api/v2/demo-videos/')){
    const avi=/\.avi$/i.test(source);
    const image=avi||source.startsWith('data:image/')||/\/frame(?:\?|$)/.test(source)||/\.(jpg|jpeg|png)$/i.test(source);
    if(image){
      reviewImgWrap.classList.remove('hide');reviewImg.onerror=()=>notice('The saved evidence frame could not be loaded.');
      reviewImg.src=avi?source+'/frame?idx=0':source;previewTitle.textContent='Evidence frame';
    }else{
      reviewVideoWrap.classList.remove('hide');reviewVideo.onerror=()=>notice('The recording could not be played in this browser.');
      reviewVideo.src=source;
      previewTitle.textContent=shortClip?'Video playback · 24-frame excerpt':'Video playback';
    }
  }else{notice('No supported preview is available for this media source.');}

  if(run.flagged_evidence&&run.flagged_evidence.length){
    evidenceGalleryWrap.classList.remove('hide');
    evidenceChips.replaceChildren(...run.flagged_evidence.map((ev, idx) => {
      const chip = uiButton('Frame #' + (ev.frame_idx ?? idx) + ' · confidence ' + (ev.conf ?? '—'),
        () => inspectEvidenceFrame(idx));
      chip.disabled = shortClip && ev.frame_idx >= 24;
      if (chip.disabled) chip.title = 'Outside the saved excerpt';
      return chip;
    }));
  }
}

function inspectEvidenceFrame(idx){
  const run=allRuns.find(r=>r.run_id===selectedRunId);
  if(!run||!run.flagged_evidence||!run.flagged_evidence[idx]) return;
  const ev=run.flagged_evidence[idx];
  if(run.input_clip&&run.input_clip.endsWith('.avi')){
    reviewImgWrap.classList.remove('hide');
    reviewVideoWrap.classList.add('hide');
    reviewImg.src=`/api/v2/demo-videos/${run.input_clip}/frame?idx=${ev.frame_idx||0}`;
  }else if(reviewVideo&&!reviewVideoWrap.classList.contains('hide')){
    if(ev.frame_idx!=null){
      reviewVideo.currentTime=Math.max(0,ev.frame_idx/(["ldpolyp_clip01.mp4","sun_seg_seq01.mp4"].includes(run.input_clip)?15:(run.fps||30.0)));
      reviewVideo.play().catch(()=>{});
    }
  }
}

async function submitRunReview(decision){
  if(!selectedRunId) return alert('Select a run to review first');
  const reason=reviewReason.value.trim();
  reviewFeedback.textContent=`Submitting clinician ${decision}...`;
  reviewFeedback.style.color='var(--accent)';

  try{
    const res=await chakraFeedback.request('Save review',`/api/v2/runs/${selectedRunId}/review`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        decision:decision,
        reason:reason,
        reviewer_id:'DR-GOKUL-R'
      })
    });
    const d=await res.json();
    if(res.ok){
      reviewFeedback.textContent=`Run ${selectedRunId} successfully recorded as ${decision.toUpperCase()} (FL-eligible: true).`;
      await loadReviewTab();
      await loadRuns();
    }else{
      reviewFeedback.textContent=`Error: ${d.detail}`;
    }
  }catch(e){
    reviewFeedback.textContent=`Submission failed: ${e}`;
  }
}

async function exportFlManifest(){
  try{
    const res=await chakraFeedback.request('Prepare manifest','/api/v2/runs/export-fl-manifest');
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob=await res.blob();
    const url=window.URL.createObjectURL(blob);
    const a=document.createElement('a');
    a.href=url;
    a.download='chakra_fl_dataset_manifest.jsonl';
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  }catch(e){
    alert('Failed to export FL manifest: '+e);
  }
}

async function initializeAdmin() {
  const response = await fetch('/api/v2/session');
  if (!response.ok) throw new Error('Session unavailable');
  const session = await response.json();
  deploymentProject.textContent = session.project;
  deploymentRegion.textContent = workerAppRegion.textContent = session.region;
  workerVisionRegion.textContent = session.vision_region || 'Unspecified';
  const operator = session.role === 'operator';
  const nav = [...document.querySelectorAll('.side button.nav')];
  const menu = document.querySelector('.mobile-sections');
  for (const index of operator ? [3, 4, 5, 6] : [0]) {
    nav[index].hidden = true;
    if (menu.options[index]) menu.options[index].disabled = true;
  }
  document.getElementById(operator ? 'docLink' : 'phoneLink').hidden = true;
  await Promise.all([warmup(), loadCatalog(), ...(operator ? [loadClips(), mintRoom()] : [])]);
}
initializeAdmin().catch(() => { gpuTxt.textContent = 'Session or service unavailable'; });
