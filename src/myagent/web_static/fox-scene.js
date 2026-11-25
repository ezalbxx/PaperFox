/* Articulated cut-paper sculpture. Lengths are in tabletop scene units. */
function createPaperStudio(canvas) {
  const T = THREE, vec = (...v) => new T.Vector3(...v);
  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(32,1,.1,40);
  const renderer = new T.WebGLRenderer({canvas,alpha:true,antialias:true,preserveDrawingBuffer:true});
  renderer.setClearColor(0,0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  renderer.outputColorSpace = T.SRGBColorSpace;
  const rig = (parent,x=0,y=0,z=0) => {
    const group = new T.Group(); parent.add(group); group.position.set(x,y,z); return group;
  };
  // A repeatable paper fibre and tooth texture shared by the folded surfaces.
  let seed=531;
  const random=()=>((seed=(1664525*seed+1013904223)>>>0)/4294967296);
  const grain=document.createElement('canvas');grain.width=grain.height=256;
  const g=grain.getContext('2d');const pixels=g.createImageData(256,256);
  for(let i=0;i<pixels.data.length;i+=4){
    const n=216+36*random();pixels.data.set([n,n,n,255],i);
  }
  g.putImageData(pixels,0,0);
  for(let i=0;i<1100;i++){
    const x=random()*256,y=random()*256;
    g.strokeStyle=random()>.5?'#79513429':'#ffffff7a';g.lineWidth=.65;
    g.beginPath();g.moveTo(x,y);g.lineTo(x+2+random()*9,y-1+random()*3);g.stroke();
  }
  const fibre=new T.CanvasTexture(grain);fibre.wrapS=fibre.wrapT=T.RepeatWrapping;
  const paper=color=>new T.MeshStandardMaterial({color,map:fibre,bumpMap:fibre,bumpScale:.009,
    roughness:.94,side:T.DoubleSide,flatShading:true});
  const orange=paper('#c47242'),sun=paper('#dc9056'),rust=paper('#9b5237'),
    ivory=paper('#f5e8d3'), blush=paper('#d8b797'), ink=paper('#38232a'), inner=paper('#a36251');
  function mesh(parent,geometry,material) {
    const obj=new T.Mesh(geometry,material);parent.add(obj);obj.castShadow=obj.receiveShadow=true;return obj;
  }
  function triangle(parent,a,b,c,mat) {
    const geom=new T.BufferGeometry();geom.setAttribute('position',new T.Float32BufferAttribute([...a,...b,...c],3));
    const A=vec(...a),ab=vec(...b).sub(A),ac=vec(...c).sub(A);
    const len=ab.length(),u=ac.dot(ab.normalize());
    geom.setAttribute('uv',new T.Float32BufferAttribute([0,0,len,0,u,Math.sqrt(Math.max(0,ac.lengthSq()-u*u))],2));
    geom.computeVertexNormals();return mesh(parent,geom,mat);
  }
  // Longitudinal sections define the silhouette; explicit material zones keep the mask and bib continuous.
  function hull(parent,sections,select,n=8){
    const rings=sections.map(([z,y,w,h])=>Array.from({length:n},(_,i)=>{
      const angle=(i+.5)*2*Math.PI/n;return [w*Math.sin(angle),y+h*Math.cos(angle),z];
    }));
    for(let k=1;k<rings.length;k++)for(let i=0;i<n;i++){
      const j=(i+1)%n,a=rings[k-1][i],b=rings[k-1][j],c=rings[k][j],d=rings[k][i];
      triangle(parent,a,b,d,select(k,i,0));triangle(parent,b,c,d,select(k,i,1));
    }
    for(const k of [0,rings.length-1]){
      const center=[0,sections[k][1],sections[k][0]];
      rings[k].forEach((p,i)=>triangle(parent,center,p,rings[k][(i+1)%n],select(Math.max(k,1),i,0)));
    }
  }
  function box(parent,w,h,d,mat,x,y,z){
    const m=mesh(parent,new T.BoxGeometry(w,h,d),mat);m.position.set(x,y,z);return m;
  }
  const root=rig(scene), torso=rig(root);
  hull(torso,[[-.99,.73,.12,.19],[-.77,.77,.40,.44],[-.27,.8,.47,.47],[.33,.92,.405,.51],[.56,1,.28,.39]],
    (k,i,j)=>i===7?sun:i===3||i===4?rust:(k===4&&i===2?ivory:orange));
  // Layered haunch and shoulder folds cast narrow shadows across the flank.
  for(const side of [-1,1]){
    const panel=(a,b,c,mat)=>triangle(torso,...[a,b,c].map(([x,y,z])=>[side*x,y,z]),mat);
    panel([.28,1.14,-.80],[.468,.86,-.42],[.362,.47,-.68],sun);
    panel([.362,.47,-.68],[.468,.86,-.42],[.40,.62,-.29],orange);
    panel([.31,1.25,.21],[.433,.90,.13],[.34,.52,.36],sun);
    panel([.31,1.25,.21],[.34,.52,.36],[.30,.92,.51],orange);
  }
  const neck=rig(torso,0,.93,.38);
  hull(neck,[[-.18,.13,.32,.35],[.05,.27,.34,.42],[.27,.36,.25,.28]],(k,i)=>[2,3,4,5].includes(i)?ivory:orange);
  triangle(neck,[-.24,.35,.24],[.23,.35,.24],[.045,-.27,.22],ivory);
  const head=rig(neck,0,.34,.09);
  hull(head,[[-.35,.10,.28,.28],[-.14,.14,.51,.42],[.12,.12,.48,.37],[.37,.05,.29,.20],[.62,.03,.10,.095]],
    (k,i,j)=>[2,3,4].includes(i)||i===5&&k>2?ivory:i===7?sun:orange);
  hull(head,[[.605,.049,.106,.083],[.706,.055,.043,.04]],()=>ink);
  const ears=[];
  for(const side of [-1,1]){
    const ear=rig(head,side*.29,.37,-.12);ears.push(ear);
    const a=[side*-.145,-.03,.135],b=[side*.22,-.10,.068],tip=[side*.17,.50,-.105],rear=[side*.035,-.04,-.19];
    triangle(ear,a,b,tip,sun);triangle(ear,a,tip,rear,orange);triangle(ear,b,rear,tip,rust);
    triangle(ear,[side*-.082,.016,.121],[side*.157,-.024,.082],[side*.153,.392,-.050],inner);
    // Raised cheek pleat and smiling ink crease, mirrored on the two sides.
    triangle(head,[side*.494,.11,.085],[side*.355,.125,.32],[side*.54,-.086,-.19],sun);
    // Project the ink onto the cheek facets so the far eyelid stays on the silhouette.
    head.updateWorldMatrix(true,true);
    const surface=head.children.filter(child=>child.isMesh);
    const probe=new T.Raycaster(),points=[];
    for(let n=0;n<=12;n++){
      const u=n/12,origin=vec(side,.19+.041*Math.sin(Math.PI*u),.16+.20*u);
      probe.set(head.localToWorld(origin),vec(-side,0,0).transformDirection(head.matrixWorld));
      const hit=probe.intersectObjects(surface,false)[0];
      if(hit){const point=head.worldToLocal(hit.point);point.x+=side*.006;points.push(point);}
    }
    if(points.length>=2)mesh(head,new T.TubeGeometry(new T.CatmullRomCurve3(points),14,.009,5,false),ink);
  }
  // Each pleat has a mountain ridge, a shaded return and a visible cut edge.
  const cutPaper = paper('#e6c8a2');
  function pleat(parent, a, b, c, ridge, lit, shade, edge){
    triangle(parent,b,c,ridge,shade);
    triangle(parent,c,a,ridge,edge);
    // Expose a narrow strip of paper core along the raised lip of this fold.
    const peak = vec(...ridge);
    const returnPoint = peak.clone().lerp(vec(...a), .065).toArray();
    const edgePoint = vec(...b).lerp(vec(...a), .016).toArray();
    // Split the face along the lip so the two materials never overlap.
    triangle(parent,b,ridge,returnPoint,cutPaper);
    triangle(parent,b,returnPoint,edgePoint,cutPaper);
    triangle(parent,edgePoint,returnPoint,a,lit);
  }
  for(const sign of [-1,1]){
    const mirror=p=>[sign*p[0],p[1],p[2]];
    const fold=(parent,points,...palette)=>pleat(parent,...points.map(mirror),...palette);
    fold(head,[[.475,.13,.12],[.555,-.075,-.18],[.12,-.074,.55],[.385,-.043,.265]],ivory,blush,ivory);
    fold(head,[[.08,.46,-.13],[.443,.285,.08],[.19,.237,.36],[.265,.335,.115]],sun,orange,sun);
    fold(neck,[[.03,.41,.29],[.30,.19,.22],[.07,-.31,.256],[.12,.08,.35]],ivory,blush,ivory);

    const ear=ears[sign===1?1:0];
    fold(ear,[[-.10,.015,.14],[.18,-.036,.098],[.156,.435,-.067],[.057,.092,.092]],inner,rust,blush);
  }
  const bite=rig(head,0,-.012,.655);
  const tail=rig(torso,0,.70,-.72);
  hull(tail,[[.02,0,.15,.15],[-.30,.07,.27,.24],[-.60,.24,.35,.32],[-.81,.48,.32,.35],[-.94,.71,.23,.26],[-.98,1,.12,.17],[-.92,1.24,.012,.02]],
    (k,i,j)=>k>=5?ivory:k===4&&i===7?ivory:i===7?sun:orange);
  for(const sign of [-1,1]){
    const points=[[.21,.39,-.48],[.34,.62,-.73],[.13,.92,-.92],[.322,.68,-.77]];
    pleat(tail,...points.map(([x,y,z])=>[sign*x,y,z]),sun,orange,rust);
  }
  tail.rotation.z=.32;
  const legs=[];
  for(const z of [-.61,.33])for(const side of [-1,1]){
    const upper=rig(root,side*.255,.68,z);
    const lower=rig(upper,0,-.33,z<0?.12:-.055);
    function segment(parent,from,to,r1,r2,mat){
      const delta=vec(...to).sub(vec(...from));
      const m=mesh(parent,new T.CylinderGeometry(r2,r1,delta.length(),5),mat);
      m.position.copy(vec(...from).lerp(vec(...to),.5));m.quaternion.setFromUnitVectors(vec(0,1,0),delta.normalize());
    }
    segment(upper,[0,.10,0],lower.position.toArray(),.159,.102,orange);
    segment(lower,[0,0,0],[0,-.30,.065],.108,.069,rust);
    hull(lower,[[.005,-.285,.064,.056],[.09,-.29,.091,.065],[.23,-.307,.052,.036]],()=>ink);
    legs.push({upper,lower,front:z>0,near:side===1});
  }
  scene.add(new T.HemisphereLight(0xfff7eb,0xac9c91,1.22));
  function light(color,strength,x,y,z,shadow){
    const l=new T.DirectionalLight(color,strength);l.position.set(x,y,z);scene.add(l);
    if(shadow){l.castShadow=true;l.shadow.mapSize.set(1024,1024);Object.assign(l.shadow.camera,{left:-3,right:3,top:3,bottom:-3});l.shadow.normalBias=.006;l.shadow.bias=-.0003;}
  }
  light(0xfff3df,1.95,-3,6,4,true);
  light(0xdfebf2,.72,4,2,3);
  light(0xffdfba,.92,2,4,-4);
  const desk=rig(scene);const wood=paper('#f4e9d8'),edge=paper('#c5aa99');
  for(let i=0;i<4;i++){
    const leaf=box(desk,3.24,.018,3.66,i%2?wood:edge,0,-.078+i*.022,.13);
    leaf.rotation.y=(i-3)*.047;leaf.position.x=(3-i)*.028;
  }
  function poseFox(t){
    const smooth=(a,b)=>{const x=Math.max(0,Math.min(1,(t-a)/(b-a)));return x*x*(3-2*x)};
    const down=smooth(.48,1.70)-smooth(1.89,2.92);
    const place=smooth(3.38,4.53)-smooth(4.72,5.62);
    const swivel=smooth(2.1,3.53)-smooth(5,6.25);
    const reach=smooth(5.05,5.69)-smooth(6.05,6.7);
    torso.position.x=.19*swivel;
    torso.position.y=-.20*down-.17*place+.012*Math.sin(t*3);
    torso.rotation.x=.27*down+.19*place;neck.rotation.y=-.13*down+.82*swivel;
    neck.rotation.x=.81*down+.70*place;
    head.rotation.x=.40*down+.39*place-.11*Math.sin(t*2)*(1-down)*(1-place);
    tail.rotation.y=-.58+.16*Math.sin(t*3.2)+.29*swivel;tail.rotation.x=.10*Math.sin(t*2.3)-.17*down;
    ears.forEach((e,i)=>{e.rotation.x=.11*Math.sin(t*3+i*.4)-.22*down;e.rotation.z=(i?1:-1)*(.05+.11*Math.exp(-12*(t-6.6)**2));});
    for(const l of legs){
      const lift=l.front&&l.near?reach:0;
      l.upper.rotation.set(-.98*lift+.06*down,0,.48*lift);
      l.lower.rotation.set(-.44*lift,0,0);
    }
    root.updateMatrixWorld(true);return bite.getWorldPosition(vec());
  }
  const collect=poseFox(1.70), release=poseFox(4.53);
  // Set the pile and loose sheet at the actual world-space contact points of the character.
  const pageW=.88,pageL=.83;
  const ground=.022;
  const pickupHeight=collect.y,releaseHeight=release.y;
  function alignBite(t){
    const dip=(center,width)=>Math.exp(-((t-center)**2)/(width*width));
    torso.position.y+=(ground-pickupHeight)*dip(1.70,.43)+(.12-releaseHeight)*dip(4.53,.47);
    root.updateMatrixWorld(true);return bite.getWorldPosition(vec());
  }
  const stack=rig(scene,release.x+.065,0,release.z+pageL/2+.045);
  const sheets=[paper('#fcf2e3'),paper('#d4bdd0')];
  for(let i=0;i<8;i++){
    const m=box(stack,pageW,.012,pageL,sheets[i%2],.013*Math.sin(i*5),.018+i*.013,0);
    m.rotation.y=.028*Math.sin(i*2);
  }
  const art=document.createElement('canvas');art.width=512;art.height=512;
  const a=art.getContext('2d');a.fillStyle='#fff4df';a.fillRect(0,0,512,512);
  a.fillStyle='#a94130';a.fillRect(36,41,67,31);a.fillStyle='#fff6e6';a.font='bold 21px Arial';a.fillText('PDF',48,64);
  a.fillStyle='#402f3b';a.font='bold 32px Georgia';a.fillText('Experiment report',35,120);
  for(let i=0;i<7;i++){a.fillStyle='#b2a3aa';a.fillRect(37,151+i*17,140+(i%3)*20,4);}
  for(let i=0;i<5;i++){a.fillStyle=i===4?'#bb5538':'#c5a3ae';a.fillRect(282+i*32,255-i*18,20,32+i*18);}
  a.strokeStyle='#ba5b45';a.lineWidth=4;a.beginPath();
  [0,1,2,3,4,5].forEach((n)=>{const x=43+n*79,y=419-n*10+Math.sin(n*2)*20;n?a.lineTo(x,y):a.moveTo(x,y);});a.stroke();
  const print=new T.CanvasTexture(art);print.colorSpace=T.SRGBColorSpace;
  const page=mesh(scene,new T.PlaneGeometry(pageW,pageL,14,18),new T.MeshStandardMaterial({map:print,side:T.DoubleSide,roughness:.94}));
  const attr=page.geometry.attributes.position,base=attr.array.slice();
  const work=rig(scene), pencil=rig(work);
  const ferrule=paper('#bb964a'),lacquer=paper('#366a63');
  function rod(parent,a,b,r1,r2,mat){
    const axis=vec(...b).sub(vec(...a));
    const m=mesh(parent,new T.CylinderGeometry(r2,r1,axis.length(),8),mat);
    m.position.copy(vec(...a).lerp(vec(...b),.5));m.quaternion.setFromUnitVectors(vec(0,1,0),axis.normalize());return m;
  }
  rod(pencil,[0,0,0],[0,.035,0],.003,.012,ink);
  rod(pencil,[0,.035,0],[0,.14,0],.012,.038,ivory);
  rod(pencil,[0,.14,0],[0,1.48,0],.038,.038,lacquer);
  rod(pencil,[0,1.48,0],[0,1.56,0],.039,.039,ferrule);
  const pad=rig(work,.36,.032,1.17);
  const sheetMat=new T.MeshStandardMaterial({map:print,roughness:.93});
  const manuscript=box(pad,1.12,.035,.93,wood,0,0,0);
  const cover=mesh(pad,new T.PlaneGeometry(1.12,.93),sheetMat);
  cover.rotation.x=-Math.PI/2;cover.position.y=.019;
  const cards=rig(work);
  const tabColors=['#9ab7a1','#d39363','#879cb1'].map(paper);
  const tabs=tabColors.map((m,i)=>{
    const card=rig(cards);box(card,.49,.022,.63,wood,0,0,0);
    box(card,.19,.01,.08,m,-.10,.019,-.25);
    for(let n=0;n<3;n++)box(card,.29-.043*n,.006,.012,edge,0,.016,-.08+n*.074);
    return card;
  });
  const chart=rig(work,-.28,.06,1.40);
  const bars=tabs.map((_,i)=>box(chart,.13,1,.12,tabColors[i],-.20+.20*i,0,0));
  const strokes=rig(pad),graphite=paper('#545066');
  const lines=Array.from({length:4},(_,i)=>box(strokes,1,.008,.015,graphite,0,.026,.02+i*.07));
  const idleLeaf=mesh(scene,new T.PlaneGeometry(1.06,.85,28,12),new T.MeshStandardMaterial({map:print,side:T.DoubleSide,roughness:.93}));
  const leafPos=idleLeaf.geometry.attributes.position,leafRest=leafPos.array.slice();
  const idleBase=rig(scene,.22,.019,1.05);
  for(let i=0;i<4;i++){const leaf=box(idleBase,1.06,.01,.85,sheets[i%2],0,.010*i,.004*i);leaf.rotation.y=.008*i;}
  function leafPoint(u,v,bend){
    const a=bend*(.26+.74*u)*(.78+.22*v);
    return vec(-.31+1.06*u*Math.cos(a),.065+1.06*u*Math.sin(a),.625+.85*v+.026*u*Math.sin(a));
  }
  function idleFlip(t){
    const bend=.06+.72*(.5-.5*Math.cos(t*1.24));
    for(let i=0;i<leafPos.count;i++){
      const p=leafPoint(.5+leafRest[3*i]/1.06,.5-leafRest[3*i+1]/.85,bend);
      leafPos.setXYZ(i,p.x,p.y,p.z);
    }
    leafPos.needsUpdate=true;idleLeaf.geometry.computeVertexNormals();idleLeaf.frustumCulled=false;
    const leg=legs.find(l=>l.front&&l.near);
    const toe=leafPoint(.83,.10,bend);toe.y+=.035;
    const upperAxis=leg.lower.position.clone(),lowerAxis=vec(0,-.307,.215);
    const delta=toe.sub(leg.upper.position),len=delta.length(),unit=delta.clone().normalize();
    const pole=vec(.13,.21,-1);pole.addScaledVector(unit,-pole.dot(unit)).normalize();
    const l1=upperAxis.length(),l2=lowerAxis.length(),stretch=Math.max(1,len/(l1+l2-.002));
    const reach=len/stretch,along=(l1*l1-l2*l2+reach*reach)/(2*reach);
    const joint=unit.clone().multiplyScalar(along).addScaledVector(pole,Math.sqrt(Math.max(0,l1*l1-along*along)));
    leg.upper.quaternion.setFromUnitVectors(upperAxis.normalize(),joint.clone().normalize());
    leg.upper.scale.setScalar(stretch);
    const shin=delta.divideScalar(stretch).sub(joint).applyQuaternion(leg.upper.quaternion.clone().invert());
    leg.lower.quaternion.setFromUnitVectors(lowerAxis.normalize(),shin.normalize());
    neck.rotation.x=.20+.13*bend;neck.rotation.y=.26+.12*bend;head.rotation.x=.14+.07*bend;
  }
  function act(t,mode){
    const wave=Math.sin(t*1.6),scan=Math.sin(t*2.8);
    poseFox(0);
    for(const l of legs){l.upper.scale.setScalar(1);l.lower.scale.setScalar(1);}
    torso.position.y=.014*wave;tail.rotation.y=-.55+.16*Math.sin(t*1.7);
    tail.rotation.x=.13*Math.sin(t*1.1);
    ears.forEach((ear,i)=>ear.rotation.z=(i?1:-1)*(.10+.16*Math.pow(Math.max(0,Math.cos(t*2+i)),12)));
    neck.rotation.y=.14*wave;head.rotation.x=-.15+.045*wave;
    cards.visible=mode==='structure';chart.visible=mode==='execution';
    pencil.visible=strokes.visible=mode==='writing';pad.visible=!['idle','structure','materials','formatting'].includes(mode);
    if(mode==='idle'){idleFlip(t);return;}
    neck.rotation.x=.49;head.rotation.x=.16;
    if(mode==='ready'){neck.rotation.x=-.10;head.rotation.x=-.18;pad.rotation.z=0;}
    if(mode==='planning'){neck.rotation.y=.27*scan;head.rotation.x=.28+.08*wave;}
    if(mode==='execution'){bars.forEach((b,i)=>{b.scale.y=.15+.14*(1+Math.sin(t*2+i));b.position.y=b.scale.y/2;});neck.rotation.y=-.24+.19*wave;}
    if(mode==='structure'){
      tabs.forEach((card,i)=>{const u=(1+Math.sin(t*1.5-i*1.3))/2;card.position.set(-.47+i*.47,.045+u*.04,1.25+.14*u);card.rotation.y=.09*(i-1)*u;});
      neck.rotation.y=.31*wave;legs.find(l=>l.front&&l.near).upper.rotation.x=-.45-.29*wave;
    }
    if(mode==='writing'){
      const row=Math.floor(t*1.18)%4,u=t*1.18%1;
      neck.rotation.y=.20+.27*(u-.5);torso.position.y=-.07;
      head.rotation.x=.30+.018*Math.sin(t*20);
      const tip=vec(pad.position.x-.35+.66*u,.061,pad.position.z+.02+row*.07);
      root.updateMatrixWorld(true);const axis=bite.getWorldPosition(vec()).sub(tip);
      pencil.position.copy(tip);pencil.quaternion.setFromUnitVectors(vec(0,1,0),axis.normalize());
      lines.forEach((line,i)=>{const length=.66*(i<row?1:i===row?u:0);line.scale.x=Math.max(.001,length);line.position.x=-.35+length/2;});
    }
  }
  // Static facets on one joint share a draw call per material.
  function batchFacets(parent){
    for(const child of parent.children.slice())if(child.isGroup)batchFacets(child);
    const batches=new Map();
    for(const m of parent.children)if(m.isMesh && m.geometry.attributes.position.count===3){
      if(!batches.has(m.material))batches.set(m.material,[]);batches.get(m.material).push(m);
    }
    for(const [mat,items] of batches){if(items.length<2)continue;
      const geom=new T.BufferGeometry();
      for(const [key,dim] of [['position',3],['normal',3],['uv',2]]){
        geom.setAttribute(key,new T.Float32BufferAttribute(items.flatMap(m=>Array.from(m.geometry.attributes[key].array)),dim));
      }
      items.forEach(m=>{parent.remove(m);m.geometry.dispose();});mesh(parent,geom,mat);
    }
  }
  batchFacets(root);
  function render(t,yaw,pitch,width,height,mode="materials"){
    idleLeaf.visible=idleBase.visible=mode==="idle";
    const sorting=mode==="materials"||mode==="formatting";work.visible=!sorting;page.visible=sorting;stack.visible=sorting;
    if(sorting){
    t=mode==="formatting"?3.1+t%5.5:t%8.6;
    poseFox(t);const grip=alignBite(t);
    const carrying=t>=1.70&&t<=4.53;
    const slide=T.MathUtils.smoothstep(t,5.62,6.02);
    const anchor=t<1.70?vec(collect.x,ground,collect.z):carrying?grip:vec(release.x+.065*slide,.12,release.z+.045*slide);
    // Plant the front paw at the near edge, then move the same distance as the page.
    const activeLeg=legs.find(l=>l.front&&l.near);
    const reach=T.MathUtils.smoothstep(t,5.02,5.62)-T.MathUtils.smoothstep(t,6.04,6.75);
    if(reach>0){
      const shoulder=activeLeg.upper.position;
      const restEnd=vec(0,-.63,.10);
      const target=vec(release.x-.33+.065*slide,.155+.09*Math.sin(Math.PI*reach),release.z+.035+.045*slide);
      const desired=restEnd.clone().lerp(target.sub(shoulder),reach);
      const joint=vec(0,-.32,-.055).lerp(desired.clone().multiplyScalar(.48).add(vec(.05,.065,-.075)),reach);
      activeLeg.upper.rotation.set(0,0,0);activeLeg.lower.rotation.set(0,0,0);
      const first=activeLeg.lower.position.clone();
      activeLeg.upper.quaternion.setFromUnitVectors(first.normalize(),joint.clone().normalize());
      const scale=joint.length()/activeLeg.lower.position.length();activeLeg.upper.scale.setScalar(scale);
      const localEnd=desired.clone().sub(joint).applyQuaternion(activeLeg.upper.quaternion.clone().invert()).divideScalar(scale);
      const foot=vec(0,-.307,.215);
      activeLeg.lower.quaternion.setFromUnitVectors(foot.clone().normalize(),localEnd.clone().normalize());
      activeLeg.lower.scale.setScalar(localEnd.length()/foot.length());
    }else{activeLeg.upper.scale.setScalar(1);activeLeg.lower.scale.setScalar(1);}
    const raised=carrying?Math.min(1,Math.max(0,(anchor.y-.12)/.62)):0;
    for(let i=0;i<attr.count;i++){
      const x=base[i*3],z=pageL/2-base[i*3+1],s=z/pageL;
      const sag=raised*(.46*s**1.4+.045*Math.sin(t*8-s*3)*s);
      attr.setXYZ(i,x,Math.max(ground-anchor.y,.002-sag)+raised*x*x*.20,z*(1-.25*raised));
    }
    page.position.copy(anchor);page.rotation.y=raised*.15*Math.sin(t*2);
    attr.needsUpdate=true;page.geometry.computeVertexNormals();page.frustumCulled=false;
    }else{act(t,mode);}
    const aspect=width/height;
    camera.aspect=aspect;camera.updateProjectionMatrix();
    const radius=Math.max(5.63,5.75/aspect);
    const az=.89+yaw,el=.35+pitch;
    camera.position.set(radius*Math.cos(el)*Math.sin(az),.84+radius*Math.sin(el),.06+radius*Math.cos(el)*Math.cos(az));
    camera.lookAt(0,.84,.06);renderer.render(scene,camera);
  }
  return {render,resize(w,h){renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setSize(w,h,false);}};
}
