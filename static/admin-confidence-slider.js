(()=>{
 const slider=document.getElementById('confRange'), wrap=slider.parentElement, wheel=wrap.querySelector('img');
 function render(){
   const fraction=(slider.valueAsNumber-Number(slider.min))/(Number(slider.max)-Number(slider.min));
   const diameter=parseFloat(getComputedStyle(wrap).getPropertyValue('--wheel'));
   const distance=fraction*Math.max(0,wrap.clientWidth-diameter);
   wrap.style.setProperty('--fill',(100*fraction)+'%');
   wrap.style.setProperty('--travel',distance+'px');
   wrap.style.setProperty('--angle',(distance*360/(Math.PI*diameter))+'deg');
 }
 function enable(){if(!wheel.naturalWidth)return;render();wrap.classList.add('ready')}
 wheel.addEventListener('load',enable);enable();
 slider.addEventListener('input',render);new ResizeObserver(render).observe(wrap);
})();
