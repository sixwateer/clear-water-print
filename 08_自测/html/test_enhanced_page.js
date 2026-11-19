/* 增强版页面：验证内嵌算法在两张真实图上的效果（自动判断极性、笔画/插值两模式、框外不变） */
const fs=require('fs'),vm=require('vm');
const HTML=fs.readFileSync('D:/去水印/02_HTML版/净像去水印_增强版_双击即用.html','utf8');
let pass=0,fail=0;
function ok(name,cond,msg){if(cond){pass++;console.log('PASS  '+name)}else{fail++;console.log('FAIL  '+name+'  '+(msg||''))}}

// 1) 结构与自包含检查
ok('单文件自包含(无外部src/href)',!/<script[^>]+src=/.test(HTML)&&!/<link[^>]+href=/.test(HTML));
ok('内嵌两张示例图Base64',(HTML.match(/data:image\/(jpeg|png);base64,/g)||[]).length===2);
ok('三种修复模式',/智能/.test(HTML)&&/平滑背景/.test(HTML)&&/物体表面/.test(HTML));

// 2) 抽取算法到沙箱
let code=HTML.match(/<script>([\s\S]*?)<\/script>/)[1];
const cut=code.indexOf('   界面交互');
code=code.slice(0,code.lastIndexOf('/*',cut))+'\n;globalThis.processBox=processBox;';
function el(){return{style:{},dataset:{},value:'',textContent:'',innerHTML:'',classList:{add(){},remove(){},toggle(){},contains(){return false}},addEventListener(){},getContext(){return{createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)})}}}}
const sb={document:{getElementById(){return el()},createElement(){return el()},addEventListener(){}},window:{addEventListener(){}},console,setTimeout,Math,Date,JSON,Object,Array,String,Number,Boolean,RegExp,Error,Uint8Array,Uint8ClampedArray,Float32Array,Uint32Array,parseInt,parseFloat,isNaN,performance:{now:()=>Date.now()},ImageData:class{constructor(d,w,h){this.data=d;this.width=w;this.height=h}}};
vm.createContext(sb);vm.runInContext(code,sb);

function loadPx(name){const d=JSON.parse(fs.readFileSync('D:/去水印/08_自测/html/_tmp/px_'+name+'.json','utf8'));return{w:d.w,h:d.h,data:Uint8ClampedArray.from(d.data)}}

// 3) 图1：半透明水印图，平滑模式整框去除
{
  const p=loadPx('wood'),orig=Uint8ClampedArray.from(p.data);
  const img={data:p.data,width:p.w,height:p.h};
  const r=sb.processBox(img,{x:1062,y:2204,w:202,h:58},'smooth',1);
  ok('图1-走平滑插值模式',r.method==='smooth',r.method);
  // 框内确有变化
  let changed=0;const bx=1062,by=2204,bw=202,bh=58;
  for(let y=by;y<by+bh;y++)for(let x=bx;x<bx+bw;x++){const k=(y*p.w+x)*4;if(p.data[k]!==orig[k])changed++}
  ok('图1-框内文字被处理',changed>2000,'changed='+changed);
  // 框外逐字节不变
  const ex=Math.max(6,Math.round(Math.min(bw,bh)*0.28)); // 平滑模式自动外扩
  let outside=false;
  for(let y=2180;y<2278&&!outside;y++)for(let x=1020;x<1280;x++){
    if(x>=bx-ex&&x<bx+bw+ex&&y>=by-ex&&y<by+bh+ex)continue; // 框+外扩区
    const k=(y*p.w+x)*4;if(p.data[k]!==orig[k]){outside=true;break}
  }
  ok('图1-外扩区之外逐字节不变',!outside);
}

// 4) 图2：四处JJ，物体表面模式笔画级去除
{
  const p=loadPx('blue'),orig=Uint8ClampedArray.from(p.data);
  const img={data:p.data,width:p.w,height:p.h};
  const boxes=[[92,10,156,78],[452,322,68,76],[792,452,68,62],[187,427,96,106]];
  const rs=boxes.map(b=>sb.processBox(img,{x:b[0],y:b[1],w:b[2],h:b[3]},'stroke',1));
  ok('图2-四处均走笔画模式',rs.every(r=>r.method==='stroke'),JSON.stringify(rs.map(r=>r.method)));
  ok('图2-笔画覆盖率合理',rs.every(r=>r.cov>0.02&&r.cov<0.5),JSON.stringify(rs.map(r=>+r.cov.toFixed(3))));
  // 框外逐字节不变
  let outside=false;
  for(let y=0;y<p.h&&!outside;y++)for(let x=0;x<p.w;x++){
    let inBox=false;for(const b of boxes){
      const ex=Math.max(4,Math.round(Math.min(b[2],b[3])*0.12));
      if(x>=b[0]-ex&&x<b[0]+b[2]+ex&&y>=b[1]-ex&&y<b[1]+b[3]+ex){inBox=true;break}
    }
    if(inBox)continue;
    const k=(y*p.w+x)*4;if(p.data[k]!==orig[k]){outside=true;break}
  }
  ok('图2-外扩区之外逐字节不变',!outside);
}

console.log('\n结果: '+pass+'/'+(pass+fail)+' 通过');
process.exit(fail?1:0);
