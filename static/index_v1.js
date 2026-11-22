let curId = null;
fetch('/api/warmup').then(r=>r.json()).then(d=>{document.getElementById('gpu').textContent='Vision Ready: '+(d.gpu||d.status);});
async function run(){
  const f=document.getElementById('f').files[0]; if(!f) return alert('Select a colonoscopy frame');
  for (const input of document.querySelectorAll('input[type=number]')) if (!input.reportValidity()) return;
  curId=null;
  document.getElementById('signBtn').disabled=true;
  const fd=new FormData(); fd.append('file',f); fd.append('bbps_r',r.value); fd.append('bbps_t',t.value); fd.append('bbps_l',l.value); fd.append('withdrawal_sec',w.value);
  document.getElementById('json').textContent='Running L4 detection + Gemini 3.8 Flash...';
  const d=await (await chakraFeedback.request('Analyze upload','/api/analyze',{method:'POST',body:fd})).json();
  if (!d.report) { document.getElementById('json').textContent='Analysis unavailable'; return; }
  curId=d.report.procedure_id; document.getElementById('signBtn').disabled=false;
  document.getElementById('vmeta').textContent=`${d.vision.device} | ${d.vision.latency_ms} ms | Polyps: ${d.vision.count}`;
  document.getElementById('img').src='data:image/jpeg;base64,'+d.vision.overlay_jpg_b64;
  document.getElementById('notes').replaceChildren(...[
    ['Status',d.report.status],['Clinical',d.report.narrative.findings_summary],
    ['English',d.report.narrative.patient_discharge_english],['Tamil',d.report.narrative.patient_discharge_tamil]
  ].map(([label,value]) => uiNode('p',label+': '+value)));
  document.getElementById('json').textContent=JSON.stringify(d.report.abdm_fhir_r4,null,2);
}
async function signoff(){
  const d=await (await chakraFeedback.request('Sign off report','/api/signoff/'+curId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hitl_attested:true})})).json();
  document.getElementById('json').textContent=JSON.stringify({status:d.report.status, bigquery:d.bigquery},null,2);
}
