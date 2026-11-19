const fs=require('fs'),vm=require('vm');
const HTML=fs.readFileSync('D:/去水印/02_HTML版/净像去水印_增强版_双击即用.html','utf8');
let code=HTML.match(/<script>([\s\S]*?)<\/script>/)[1];
const cut=code.indexOf('   界面交互');
code=code.slice(0,code.lastIndexOf('/*',cut))+'\n;globalThis.processBox=processBox;globalThis.medianBlurGray=medianBlurGray;globalThis.percentile=percentile;globalThis.morph=morph;globalThis.openClose=openClose;';
function el(){return{style:{},dataset:{},value:'',textContent:'',innerHTML:'',checked:false,width:720,height:400,classList:{add(){},remove(){},toggle(){},contains(){return false}},addEventListener(){},getContext(){return{createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4),width:w,height:h}),putImageData(){},clearRect(){}}},getBoundingClientRect(){return{left:0,top:0,width:720,height:400}}}}
const els={};
const sb={document:{getElementById(id){return els[id]||(els[id]=el())},querySelector(){return null},querySelectorAll(){return[]},createElement(){return el()},addEventListener(){}},window:{addEventListener(){}},console,setTimeout,clearTimeout,Math,Date,JSON,Object,Array,String,Number,Boolean,RegExp,Error,Uint8Array,Uint8ClampedArray,Float32Array,Uint32Array,parseInt,parseFloat,isNaN,performance:{now:()=>Date.now()},ImageData:class{constructor(d,w,h){this.data=d;this.width=w;this.height=h}}};
vm.createContext(sb);vm.runInContext(code,sb);

function run(pxName,boxes,mode,sense,outName){
  const d=JSON.parse(fs.readFileSync('D:/去水印/08_自测/html/_tmp/px_'+pxName+'.json','utf8'));
  const W=d.w,H=d.h,src=Uint8ClampedArray.from(d.data);
  const imgData={data:src,width:W,height:H};
  const methods=boxes.map(b=>{
    const t=Date.now();
    const r=sb.processBox(imgData,{x:b[0],y:b[1],w:b[2],h:b[3]},mode,sense);
    r.ms=Date.now()-t;return r;
  });
  console.log(outName,mode,JSON.stringify(methods));
  fs.writeFileSync('D:/去水印/08_自测/html/_tmp/'+outName+'_out.json',JSON.stringify({w:W,h:H,data:Array.from(src)}));
}
// 图1：豆包水印，条纹图右下角。先精确定位水印位置
run('wood',[[1062,2204,202,58]],'smooth',1,'enh_wood');
// 图2：四处JJ
run('blue',[[92,10,156,78],[452,322,68,76],[792,452,68,62],[187,427,96,106]],'stroke',1,'enh_blue');
console.log('done');

// 调试：图2帆布袋JJ
const d=JSON.parse(fs.readFileSync('D:/去水印/08_自测/html/_tmp/px_blue.json','utf8'));
const W=d.w,src=Uint8ClampedArray.from(d.data);
const box=[792,452,68,62],x=box[0],y=box[1],w=box[2],h=box[3];
const exp=Math.max(4,Math.round(Math.min(w,h)*0.12));
const x1=x-exp,y1=y-exp,x2=x+w+exp,y2=y+h+exp,rw=x2-x1,rh=y2-y1;
const gray=new Uint8Array(rw*rh);
for(let j=0;j<rh;j++)for(let i=0;i<rw;i++){const k=((y1+j)*W+(x1+i))*4;gray[j*rw+i]=Math.round(0.299*src[k]+0.587*src[k+1]+0.114*src[k+2])}
let ksz=Math.max(11,(Math.min(rw,rh)/4)|1);if(ksz%2===0)ksz++;
const bg=sb.medianBlurGray(gray,rw,rh,ksz);
const pos=[],neg=[];for(let i=0;i<rw*rh;i++){const dd=gray[i]-bg[i];if(dd>0)pos.push(dd);else neg.push(-dd)}
console.log('DEBUG ksz',ksz,'rw,rh',rw,rh);
console.log('DEBUG gray min/max/mean',Math.min(...gray),Math.max(...gray),gray.reduce((a,b)=>a+b,0)/gray.length);
console.log('DEBUG bg min/max/mean',Math.min(...bg),Math.max(...bg),bg.reduce((a,b)=>a+b,0)/bg.length);
console.log('DEBUG p97',sb.percentile(pos,0.97),'n97',sb.percentile(neg,0.97),'poslen',pos.length,'neglen',neg.length);

// 调试mask: 手动复现
const th=Math.max(26,76*0.42),src2=new Float32Array(rw*rh);for(let i=0;i<rw*rh;i++)src2[i]=bg[i]-gray[i];
let raw=0;for(let i=0;i<rw*rh;i++)if(src2[i]>th)raw++;
console.log('DEBUG2 th',th.toFixed(1),'raw mask count',raw,'cov',(raw/(rw*rh)).toFixed(3));

let mm=new Uint8Array(rw*rh);for(let i=0;i<rw*rh;i++)mm[i]=src2[i]>th?1:0;
let n0=mm.reduce((a,b)=>a+b,0);
let m1=sb.openClose(mm,rw,rh);let n1=m1.reduce((a,b)=>a+b,0);
console.log('DEBUG3 openClose before',n0,'after',n1);
let m2=sb.morph(mm,rw,rh,'dilate');console.log('DEBUG3 dilate only',m2.reduce((a,b)=>a+b,0));
