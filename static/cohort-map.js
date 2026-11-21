(() => {
  const holder = document.getElementById('historyGraph');
  const dialog = document.getElementById('historyDialog');
  if (!holder || !dialog) return;
  const note = document.getElementById('patient'), detail = document.getElementById('visits');
  const bucket = 'girpolypposframesrealcolon-chakra-models';
  const make = (tag, value) => {
    const element = document.createElement(tag); element.textContent = value; return element;
  };
  let cohort, selected, activeGroup;
  const groups = ['dataset-labeled polyp', 'dataset-labeled no polyp', 'other lower-GI annotation'];
  const titles = ['Dataset-labeled polyp', 'Dataset-labeled no polyp', 'Other lower-GI annotation'];
  function select(row) {
    selected = row;
    for (const b of holder.querySelectorAll('button')) b.setAttribute('aria-pressed', String(b.textContent === row.patient_id));
    const folder = make('a', 'Open private run history in Google Cloud');
    folder.href = 'https://console.cloud.google.com/storage/browser/' + bucket + '/evaluation-runs/' + row.patient_id + '?project=girpolypposframesrealcolon';
    folder.target = '_blank'; folder.rel = 'noopener';
    detail.replaceChildren(make('h3', row.patient_id), make('p', 'Synthetic hospital UHID · ' + row.demo_uhid), make('p', 'Synthetic ABHA · ' + row.demo_abha), make('p', row.source + ' · ' + row.annotation),
      make('p', row.frames.toLocaleString() + ' original frames · ' + row.fps.toFixed(2) + ' fps'),
      make('p', 'YOLOViT · ChakraNet · PVT-PraNet · SEPNet'), folder,
      make('p', 'Each completed run includes an annotated replay and a frame log. Segmentation runs also include lossless masks.'));
    for (const [model, run] of Object.entries(row.run_notes || {})) {
      const summary = document.createElement('details');
      summary.append(make('summary', model + ' · ' + run.flagged.toLocaleString() + ' of ' + run.frames.toLocaleString() + ' frames above 0.70'),
        make('p', 'Gemini guide · ' + run.guide), make('small', run.explainer));
      detail.append(summary);
    }
  }
  function draw() {
    holder.replaceChildren();
    holder.style.cssText = 'padding:16px;border-radius:12px;background:#101521;color:#f3f5ff';
    for (const [i, group] of groups.entries()) {
      const rows = cohort.filter(r => r.label === group);
      const section = document.createElement('details');
      section.open = group === activeGroup;
      const summary = make('summary', titles[i] + ' · ' + rows.length + ' patients');
      section.append(summary);
      const nodes = document.createElement('div');
      nodes.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:8px;margin:12px 0';
      for (const row of rows) {
        const node = make('button', row.patient_id);
        node.type = 'button'; node.style.cssText = 'width:60px;height:60px;border-radius:50%;border:2px solid #d9dcec;color:white;font-size:11px;font-weight:650;cursor:pointer;background:' + ['#655299','#275c78','#376453'][i];
        node.onclick = () => { activeGroup = group; select(row); };
        nodes.append(node);
      }
      section.append(nodes); holder.append(section);
    }
    select(selected || cohort[0]);
  }
  async function load() {
    note.textContent = 'Loading cohort…';
    try {
      const response = await fetch('/v2/assets/cohort-index.json');
      if (!response.ok) throw Error();
      cohort = await response.json(); activeGroup ||= cohort[0].label;
      note.textContent = cohort.length + ' fictional patients · one original dataset video per patient';
      draw();
    } catch { note.textContent = 'Cohort unavailable. Refresh to retry.'; }
  }
  document.getElementById('openHistory').onclick = () => { dialog.showModal(); load(); };
  document.getElementById('refresh').onclick = load;
  document.getElementById('closeHistory').onclick = () => dialog.close();
})();
