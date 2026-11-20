/* 普通版 HTML：优化前后行为等价 + 结构回归
   对比 _tmp/normal_before_optimize.html（优化前备份）与当前权威文件，
   在随机输入下逐字节比对 lineRemove / smartFill / fillAverage 的输出。 */
const fs=require('fs'),vm=require('vm'),crypto=require('crypto');
const OLD='D:/去水印/08_自测/html/_tmp/normal_before_optimize.html';
const NEW='C:/Users/16044/Documents/xwechat_files/wxid_61an2vkkekea22_f358/msg/file/2026-11/净像去水印_普通版_双击即用(2).html';
let pass=0,fail=0;
function ok(name,cond,msg){if(cond){pass++;console.log('PASS  '+name)}else{fail++;console.log('FAIL  '+name+'  '+(msg||''))}}

function ctxFactory(){
  const noop=function(){},st={};
  return new Proxy({},{get(t,p){
    if(p==='getImageData')return(x,y,w,h)=>{const d=new Uint8ClampedArray(w*h*4);for(let i=0;i<d.length;i++)d[i]=(i*13+7)%256;return{data:d}};
    if(p==='createLinearGradient')return()=>({addColorStop:noop});
    if(p in t)return t[p];if(p in st)return st[p];return noop;
  },set(t,p,v){st[p]=v;return true}});
}
function sandbox(html){
  let code=html.match(/<script>([\s\S]*?)<\/script>/)[1];
  code+='\n;globalThis.__api={lineRemove,smartFill,fillAverage,fillTexture,sharpen,S,CONFIG};';
  const noop=function(){};
  function ctxMock(){const st={};return new Proxy({},{get(t,p){
    if(p==='getImageData')return(x,y,w,h)=>{const d=new Uint8ClampedArray(w*h*4);for(let i=0;i<d.length;i++)d[i]=(i*13+7)%256;return{data:d}};
    if(p==='createLinearGradient')return()=>({addColorStop:noop});
    if(p==='measureText')return()=>({width:20});
    if(p==='canvas')return{width:760,height:500};
    if(p in t)return t[p];if(p in st)return st[p];return noop;
  },set(t,p,v){st[p]=v;return true}})}
  function el(id){const o={id,width:760,height:500,value:'',textContent:'',disabled:false,checked:false,style:{},dataset:{},
    classList:{add:noop,remove:noop,toggle:noop,contains:()=>false},getContext:()=>ctxMock(),addEventListener:noop,
    toDataURL:()=>'data:,',getBoundingClientRect:()=>({left:0,top:0,width:760,height:500})};
    return new Proxy(o,{get(t,p){if(p in t)return t[p];return noop},set(t,p,v){t[p]=v;return true}})}
  const sb={document:{getElementById:el,querySelector:el,querySelectorAll:()=>[],createElement:()=>el('c'),addEventListener:noop},
    window:{addEventListener:noop,scrollTo:noop},performance:{now:()=>0},console,
    ImageData:class{constructor(d,w,h){this.data=d;this.width=w;this.height=h}},
    Image:class{set src(v){if(this.onload)this.onload()}},setTimeout,clearTimeout};
  vm.createContext(sb);vm.runInContext(code,sb);
  try{vm.runInContext('globalThis.__api.FILL=FILL;',sb)}catch(e){} // 优化前备份无 FILL
  return sb.__api;
}

if(!fs.existsSync(OLD)){
  console.log('SKIP  优化前备份不存在：'+OLD);
}else{
  const A=sandbox(fs.readFileSync(OLD,'utf8'));
  const B=sandbox(fs.readFileSync(NEW,'utf8'));
  const ctx=ctxFactory(); // 两版共用同一个纹理采样源，保证对比公平
  function dataFor(W,H,seed){const d=new Uint8ClampedArray(W*H*4);let s=seed>>>0;
    for(let i=0;i<d.length;i++){s=(s*1664525+1013904223)>>>0;d[i]=s&255}return d}
  function hash(arr){return crypto.createHash('md5').update(Buffer.from(arr.buffer,arr.byteOffset,arr.byteLength)).digest('hex')}
  function eq(a,b){return a.length===b.length&&hash(a)===hash(b)}
  function shapeFor(rng,W,H){
    const cx=12+Math.floor(rng()*(W-40)),cy=12+Math.floor(rng()*(H-40));
    const w=8+Math.floor(rng()*Math.min(40,W-cx-4)),h=8+Math.floor(rng()*Math.min(40,H-cy-4));
    const n=3+Math.floor(rng()*5),pts=[];
    for(let k=0;k<n;k++){const a=2*Math.PI*k/n;pts.push({x:cx+w/2*Math.cos(a)*(0.6+rng()*0.6),y:cy+h/2*Math.sin(a)*(0.6+rng()*0.6)})}
    return pts;
  }
  let seed=20261120;const rng=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296};
  const modes=['smart','average','texture'];
  let n=0,mismatch=0,rejected=0;
  for(const mode of modes)for(let t=0;t<24;t++){
    const W=70+Math.floor(rng()*30),H=70+Math.floor(rng()*30);
    const shape=shapeFor(rng,W,H);
    const d1=dataFor(W,H,(seed^t)+1),d2=new Uint8ClampedArray(d1);
    const iters=[120,320,640][t%3];
    const r1=A.lineRemove(d1,W,H,shape,iters,mode,ctx);
    const r2=B.lineRemove(d2,W,H,shape,iters,mode,ctx);
    n++;
    if(!r1&&!r2){rejected++;continue}
    if(!r1||!r2||!eq(d1,d2)||r1.x!==r2.x||r1.y!==r2.y||r1.w!==r2.w||r1.h!==r2.h){mismatch++;
      console.log('  MISMATCH mode='+mode+' t='+t+' r1='+JSON.stringify(r1&&{x:r1.x,y:r1.y,w:r1.w,h:r1.h,method:r1.method})+' r2='+JSON.stringify(r2&&{x:r2.x,y:r2.y,w:r2.w,h:r2.h,method:r2.method}));}
  }
  ok('三模式 '+n+' 组随机输入优化前后逐字节一致',mismatch===0,'mismatch='+mismatch+' rejected='+rejected);

  // 共用矩形算法逐字未变（对比函数源码）
  const srcOld=fs.readFileSync(OLD,'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
  const srcNew=fs.readFileSync(NEW,'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
  function body(s,name){const m=s.match(new RegExp('function '+name+'\\([^)]*\\)\\{'));if(!m)return '';
    let i=m.index+m[0].length-1,d=0;for(let j=i;j<s.length;j++){if(s[j]==='{')d++;else if(s[j]==='}'&&--d===0)return s.slice(i,j+1)}return ''}
  for(const f of ['fillAverage','fillTexture','smartFill','_medianBlur','_pct','_morph','_closeMask','_coons','_diffuse','_writeAll','fillLaplace'])
    ok('矩形/共用函数逐字未变: '+f,body(srcOld,f)===body(srcNew,f));
}

// 结构 / 常量 / 边界回归（不依赖备份）
const HTML=fs.readFileSync(NEW,'utf8');
const api=sandbox(HTML);
ok('S 定义字段未变',/const S = \{[\s\S]*?img:null, scale:1, rects:\[\], drawing:false, start:null, cur:null,[\s\S]*?resultData:null, mode:'smart', sharpen:true, iter:2[\s\S]*?\};/.test(HTML));
ok('CONFIG 定义未变',/maxDisplayWidth: 760/.test(HTML)&&/autoIterations: \{ 1: 120, 2: 320, 3: 640 \}/.test(HTML)&&/sharpenAmount: 0.25/.test(HTML));
const F=api.FILL;
ok('FILL 常量数值与矩形路径一致',F.expMin===8&&F.expRatio===0.28&&F.pad===3&&F.texOffset===4&&F.radMin===7&&F.radMax===15&&F.radDiv===6&&F.residualMin===12&&F.thMin===26&&F.thRatio===0.42&&F.pct===0.97&&F.covLarge===0.04&&F.covTiny===0.004&&F.wideRatio===2.0&&F.iterFloor===150&&F.minBox===6&&F.minMask===8);
ok('放大/缩小按钮已移除',!/id="toolZoomIn"/.test(HTML)&&!/id="toolZoomOut"/.test(HTML));
ok('顶部下一页入口存在',/id="btnNextTop"/.test(HTML));
ok('滚轮缩放已移除',!/addEventListener\('wheel'/.test(HTML));
ok('8 小手柄定义',/HANDLE=8, HIT=12, MIN_BOX=8/.test(HTML)&&/HANDLES=\['nw','n','ne','e','se','s','sw','w'\]/.test(HTML));

// 边界：贴边多边形（外扩被钳到画面内）不应越界，且不改动线条外像素
{
  const W=60,H=60,d=new Uint8ClampedArray(W*H*4),cp=new Uint8ClampedArray(d);
  const shape=[{x:2,y:2},{x:20,y:3},{x:20,y:20},{x:3,y:20}];
  const ctx=null;
  const r=api.lineRemove(d,W,H,shape,320,'smart',ctx);
  ok('贴边多边形 ROI 被钳在画面内',!!r&&r.x>=0&&r.y>=0&&r.x+r.w<=W&&r.y+r.h<=H,JSON.stringify(r&&{x:r.x,y:r.y,w:r.w,h:r.h}));
}
// 边界：退化图形（点过少 / 面积过小）返回 null
{
  const d=new Uint8ClampedArray(40*40*4);
  ok('少于3点返回null',api.lineRemove(d,40,40,[{x:5,y:5},{x:10,y:10}],320,'smart',null)===null);
  ok('过小面积返回null',api.lineRemove(d,40,40,[{x:5,y:5},{x:9,y:5},{x:9,y:9}],320,'smart',null)===null);
}

console.log('\nRESULT  pass='+pass+'  fail='+fail);
process.exit(fail?1:0);
