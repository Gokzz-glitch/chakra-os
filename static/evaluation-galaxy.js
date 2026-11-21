(() => {
 const panel = document.getElementById('tab-galaxy');
 const $ = id => document.getElementById('eg-'+id);
 const svg = $('graph'), ns = 'http://www.w3.org/2000/svg';
 const groups = ['dataset-labeled polyp','dataset-labeled no polyp','other lower-GI annotation'];
 const colors = ['#bb9bed','#82b5f2','#76d2c5'];
 const names = {yolovit_vit:'YOLOViT',chakranet:'ChakraNet',pvt_pranet:'PVT-PraNet',sepnet:'SEPNet'};
 let data, selected='SIM-001', chosen='', layout='cluster', pending=false, digest='';
 const element=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e};
 function shape(tag,attrs,parent=svg){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);parent.appendChild(e);return e;}
 function choose(patient,model=''){selected=patient;chosen=model;draw();}
 function target(group,label,action){group.setAttribute('role','button');group.setAttribute('aria-label',label);group.setAttribute('tabindex','0');group.onclick=action;group.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();action()}};}
 function draw(){
   if(!data)return;
   const runs=new Map(data.runs.map(r=>[r.patient+'/'+r.model,r]));
   const filtered=data.patients.filter(p=>(!$('filter').value||p.label===$('filter').value)&&(!$('flags').checked||data.models.some(m=>runs.get(p.patient_id+'/'+m)?.flagged>0)));
   svg.replaceChildren();const edges=shape('g',{'stroke':'#465772','stroke-width':1}),nodes=shape('g',{});
   let rank=0;
   groups.forEach((label,i)=>{
     const members=filtered.filter(p=>p.label===label);
     if(!members.length)return;
     const cx=[183,504,804][i],cy=245;
     if(layout==='cluster'){const t=shape('text',{x:cx,y:32,'text-anchor':'middle',fill:colors[i],'font-size':14});t.textContent=['Labeled polyp','Labeled no polyp','Other lower-GI'][i]+' · '+members.length;}
     members.forEach((p,j)=>{
       let x,y;
       if(layout==='cluster'){const a=j*2.39996,r=25+Math.sqrt(j/Math.max(1,members.length-1))*119;x=cx+Math.cos(a)*r;y=cy+Math.sin(a)*r*1.27}
       else{const a=rank*2.39996,r=Math.sqrt((rank+.5)/filtered.length);x=495+Math.cos(a)*435*r;y=240+Math.sin(a)*188*r;rank++}
       const id=p.patient_id;
       if(layout==='cluster')shape('line',{x1:cx,y1:cy,x2:x,y2:y,opacity:.4},edges);
       data.models.forEach((m,k)=>{const a=k*Math.PI/2+.35,ex=x+20*Math.cos(a),ey=y+20*Math.sin(a),r=runs.get(id+'/'+m);
         shape('line',{x1:x,y1:y,x2:ex,y2:ey},edges);
         const n=shape('g',{},nodes);shape('circle',{cx:ex,cy:ey,r:7,fill:'transparent'},n);
         shape('circle',{cx:ex,cy:ey,r:3.8,fill:r?'#80e6ab':'#394455',stroke:r?'#c0fbd6':'#8392a5'},n);
         shape('title',{},n).textContent=id+' · '+names[m]+' · '+(r?'Completed':'Awaiting result');
         target(n,id+' '+names[m],()=>choose(id,m));
       });
       const n=shape('g',{},nodes);shape('circle',{cx:x,cy:y,r:id===selected?10:7.5,fill:colors[i],stroke:id===selected?'white':'#253247','stroke-width':id===selected?3:1},n);
       shape('title',{},n).textContent=id+' · '+p.label;
       target(n,id,()=>choose(id));
       if(id===selected){shape('text',{x,y:y+35,'text-anchor':'middle',fill:'#fff','font-size':13,'pointer-events':'none'},nodes).textContent=id}
     });
   });
   if(!filtered.length)shape('text',{x:495,y:230,'text-anchor':'middle',fill:'#d6dcea'}).textContent='No patients match this filter.';
   if(filtered.length&&!filtered.some(p=>p.patient_id===selected)){selected=filtered[0].patient_id;chosen='';return draw()}
   const detail=$('detail');detail.replaceChildren();
   if(!filtered.length)return;
   $('patient').value=selected;
   const p=data.patients.find(p=>p.patient_id===selected);
   detail.append(element('h3',selected),element('p',p.source+' · '+p.annotation));
   for(const m of (chosen?[chosen]:data.models)){
     const r=runs.get(selected+'/'+m),box=element('div','');box.className='eg-run';
     box.append(element('strong',names[m]),element('p',r?r.frames.toLocaleString()+' frames · '+r.flagged.toLocaleString()+' flagged above 0.70 · '+r.device:'Awaiting completion record'));
     if(r){for(const file of r.files){const a=element('a',{'frames.jsonl':'Frame log','masks.zip':'Masks','replay.mp4':'Replay'}[file]||file);
       a.href='https://storage.cloud.google.com/'+data.bucket+'/evaluation-runs/'+selected+'/'+m+'/'+data.batch+'/'+encodeURIComponent(file);
       a.target='_blank';a.rel='noopener';box.append(a)}}
     detail.append(box);
   }
 }
 async function refresh(){
   if(pending||document.hidden||panel.classList.contains('hide'))return;
   pending=true;
   try{
     const response=await fetch('/api/v2/evaluation/live',{cache:'no-store'});if(!response.ok)throw Error();
     const next=await response.json();
     if(!data){for(const p of next.patients)$('patient').append(new Option(p.patient_id,p.patient_id))}
     data=next;const key=data.runs.map(r=>r.patient+r.model+r.completed).sort().join('|');
     $('count').textContent=data.runs.length+' / '+(data.patients.length*data.models.length)+' completed';
     $('time').textContent='Cloud checked '+new Date(data.checked).toLocaleTimeString();
     if(digest!==key||!svg.childElementCount){digest=key;draw()}
   }catch{$('time').textContent=data?'Refresh delayed · last checked '+new Date(data.checked).toLocaleTimeString():'Cloud results unavailable · retrying';}
   finally{pending=false}
 }
 $('layout').onchange=e=>{layout=e.target.value;draw()};$('filter').onchange=draw;$('flags').onchange=draw;
 $('patient').onchange=e=>{const id=e.target.value;$('filter').value='';$('flags').checked=false;choose(id)};
 new MutationObserver(refresh).observe(panel,{attributes:true,attributeFilter:['class']});
 document.addEventListener('visibilitychange',refresh);setInterval(refresh,5000);refresh();
})();
