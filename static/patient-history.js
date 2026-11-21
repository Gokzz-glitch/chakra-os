(() => {
const el=(name, text)=>{const n=document.createElement(name);n.textContent=text;return n};
const visits=document.getElementById('visits'), patient=document.getElementById('patient');
const refresh=document.getElementById('refresh');
const patientIds=['DEMO-PATIENT-01','DEMO-PATIENT-02'];
let selected=patientIds[0], generation=0;
const svgNS='http://www.w3.org/2000/svg';
function shape(type,attrs,parent){
  const item=document.createElementNS(svgNS,type);
  for(const [key,value] of Object.entries(attrs))item.setAttribute(key,value);
  parent.append(item);
  return item;
}
function renderGraph(data){
  const holder=document.getElementById('historyGraph');
  holder.replaceChildren();
  const svg=shape('svg',{viewBox:'0 0 730 265',width:'100%',role:'group','aria-label':'Select a synthetic patient or inspect a visit'},holder);
  svg.style.minWidth='560px';
  const links=shape('g',{'stroke':'#617993','stroke-width':2},svg);
  const nodes=shape('g',{},svg);
  function node(x,y,r,color,label,action){
    const group=shape('g',{role:'button',tabindex:'0','aria-label':label,style:'cursor:pointer'},nodes);
    shape('circle',{cx:x,cy:y,r,fill:color,stroke:'#d4deef','stroke-width':1.5},group);
    const caption=shape('text',{x,y:y+r+17,fill:'#f3f5ff','text-anchor':'middle','font-size':13},group);
    caption.textContent=label;
    group.onclick=action;
    group.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();action()}};
  }
  function edge(x,y,u,v){shape('line',{x1:x,y1:y,x2:u,y2:v},links)}
  patientIds.forEach((id,index)=>{
    const y=65+index*125;
    node(90,y,28,id===selected?'#9a82f0':'#5e547d',id,()=>{selected=id;load()});
  });
  if(!data)return;
  const records=[...data.encounters].sort((a,b)=>b.date.localeCompare(a.date));
  let row=0;
  for(const [i,visit] of records.entries()){
    const y=55+row*97;
    const visitTarget=()=>document.getElementById('visit-'+i)?.scrollIntoView({block:'nearest'});
    edge(90,65+patientIds.indexOf(selected)*125,285,y);
    node(285,y,16,'#548cda','Visit '+visit.date,visitTarget);
    for(const [j,f] of visit.findings.entries()){
      const fy=55+(row+j)*97;
      const reveal=()=>{
        const card=document.getElementById('finding-'+i+'-'+j);
        if(card){card.open=true;card.scrollIntoView({block:'nearest'});card.querySelector('summary').focus({preventScroll:true})}
      };
      edge(285,y,460,fy);node(460,fy,12,'#37a897',f.finding_id,reveal);
      edge(460,fy,640,fy);node(640,fy,10,'#d69d4e','Pathology: '+(f.pathology_status||'Unrecorded'),reveal);
    }
    row+=Math.max(1,visit.findings.length);
  }
  svg.setAttribute('viewBox','0 0 730 '+Math.max(255,65+row*97));
}
async function load(){
  const request=++generation;
  refresh.disabled=true;visits.replaceChildren();renderGraph(null);patient.textContent='Loading '+selected+'…';
  try{
    const response=await fetch('/api/v2/patients/'+encodeURIComponent(selected)+'/history',{cache:'no-store'});
    if(!response.ok)throw Error();
    const data=await response.json();
    if(request!==generation)return;
    renderGraph(data);
    patient.textContent='Synthetic case · '+data.patient_id+' · '+data.hospital_id;
    for(const [i,visit] of [...data.encounters].sort((a,b)=>b.date.localeCompare(a.date)).entries()){
      const section=el('article','');section.id='visit-'+i;section.append(el('h2',visit.date+' · '+visit.procedure_id));
      if(!visit.findings.length)section.append(el('p','No recorded findings.'));
      for(const [j,f] of visit.findings.entries()){
        const card=el('details','');card.id='finding-'+i+'-'+j;card.append(el('summary',(f.location||'Location unavailable')+' · '+f.finding_id));
        card.append(el('p','Review decision: '+(f.physician_decision||'Awaiting review')),el('small','Recorded time: '+(f.timestamp||'Unavailable')));
        const url=new URL(f.evidence_frame_url||'/',location.origin);
        if(url.origin===location.origin && /^\/api\/v2\/demo-videos\/[^/]+\/frame$/.test(url.pathname)){
          const link=el('a','Open source frame');link.href=url.href;link.target='_blank';link.rel='noopener';card.append(link);
        }else card.append(el('p','Evidence frame unavailable.'));
        const lab=f.pathology_result;
        card.append(el('p','Pathology: '+(f.pathology_status||'Unrecorded')));
        if(f.pathology_status==='SIGNED' && lab){
          card.append(el('p',lab.diagnosis||'Diagnosis unavailable'),el('small','Signed by '+(lab.signed_by||'unknown')+' · '+(lab.signed_at||'time unavailable')));
        }
        section.append(card);
      }
      visits.append(section);
    }
    if(!data.encounters.length)visits.append(el('p','No recorded visits.'));
  }catch{if(request!==generation)return;patient.textContent='History unavailable. Refresh to retry.'}finally{if(request===generation)refresh.disabled=false;}
}
refresh.onclick=load;
const dialog=document.getElementById('historyDialog');
if(dialog){
  document.getElementById('openHistory').onclick=()=>{
    dialog.showModal();
    load();
  };
  document.getElementById('closeHistory').onclick=()=>dialog.close();
}else{
  load();
}
})();
