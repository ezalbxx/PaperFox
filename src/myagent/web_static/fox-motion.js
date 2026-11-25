/* One renderer follows the visible view. Repeated progress polls retain animation time. */
function mountPaperFox(canvas) {
  const reduce=matchMedia('(prefers-reduced-motion: reduce)');
  let studio,mode=null,time=0,frame=0,last=0,yaw=0,pitch=0,drag=null,width=0,height=0;
  function draw(){if(studio&&mode&&width&&height)studio.render(time,yaw,pitch,width,height,mode);}
  function loop(now){
    frame=0;
    if(!mode||document.hidden||reduce.matches||!studio)return;
    if(last)time+=(now-last)/1000;
    last=now;draw();frame=requestAnimationFrame(loop);
  }
  function refresh(){
    cancelAnimationFrame(frame);last=0;draw();
    if(mode&&!document.hidden&&!reduce.matches&&studio)frame=requestAnimationFrame(loop);
  }
  function resize(){
    const rect=canvas.getBoundingClientRect();width=rect.width;height=rect.height;
    if(studio&&width&&height){studio.resize(width,height);draw();}
  }
  new ResizeObserver(resize).observe(canvas);
  document.addEventListener('visibilitychange',refresh);reduce.addEventListener('change',refresh);
  canvas.addEventListener('pointerdown',e=>{if(e.button===0){drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);}});
  canvas.addEventListener('pointermove',e=>{if(drag){yaw+=(e.clientX-drag[0])*.009;pitch=Math.max(-.18,Math.min(.55,pitch+(e.clientY-drag[1])*.007));drag=[e.clientX,e.clientY];draw();}});
  canvas.addEventListener('lostpointercapture',()=>drag=null);
  canvas.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();yaw+=e.key==='ArrowLeft'?-.15:.15;draw();}});
  return function show(slot,next){
    if(!slot)next=null;
    if(mode===next&&(!slot||slot===canvas.parentElement))return;
    if(slot){slot.append(canvas);if(!studio&&!canvas.hidden){
      try{studio=createPaperStudio(canvas);}catch(e){canvas.hidden=true;console.warn('PaperFox 3D unavailable',e);}
    }}
    mode=next;time=0;resize();refresh();
  };
}
