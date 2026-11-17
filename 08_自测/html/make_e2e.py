# -*- coding: utf-8 -*-
"""
生成浏览器端到端测试页：把当前交付的 HTML 复制一份，注入自动测试脚本。
测试内容：贴边识别 / 自动框 / 方向键微调 / 三模式修复 / 整图框。

用法：
    python make_e2e.py
    chrome --headless --virtual-time-budget=30000 --dump-dom _tmp/e2e.html | grep <title>
结果写在 <title> 里：E2E|OK ... |DONE
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
HTML_PATH = os.path.join(ROOT, '02_HTML版', '净像去水印_普通版_双击即用.html')
OUT = os.path.join(HERE, '_tmp', 'e2e.html')

TEST = r'''
<script>
(function(){
  var log=[];function w(m){log.push(m);document.title='E2E|'+log.join('|')}
  function ok(n,c,x){w((c?'OK ':'FAIL ')+n+(x?('('+x+')'):''))}
  loadExample();
  var t=0,timer=setInterval(function(){
    t++; if(t>100){clearInterval(timer);w('TIMEOUT');return}
    if(!baseImage)return; clearInterval(timer);
    try{
      // 1) 框贴画布边缘时的智能识别（回归：getImageData 越界会抛 IndexSizeError）
      S.rects=[{x:stage.width-60,y:stage.height-30,w:60,h:30}];S.activeBox=0;
      var e=null,d=null;
      try{d=localDetect(S.rects[0])}catch(err){e=err.message}
      ok('贴边识别',!e,e||(d.label+'/'+d.mode));
      // 2) 自动框右下角（多框后是"追加一个框"，先清空再断言）
      S.rects=[];S.activeBox=0;
      document.getElementById('toolAuto').click();
      ok('自动框',S.rects.length===1&&S.rects[S.activeBox].x>0,'x'+Math.round(S.rects[S.activeBox].x));
      // 3) 方向键微调当前框
      var bx=S.rects[S.activeBox].x;
      window.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft'}));
      ok('方向键微调',Math.abs(S.rects[S.activeBox].x-(bx-1))<0.001,(bx-1)+'->'+S.rects[S.activeBox].x);
      // 4) 最多三个框：连续画 5 次，超过上限时替换当前框
      S.rects=[];S.activeBox=0;S.tool='rect';
      for(var i=0;i<5;i++){
        S.action='draw';S.start={x:10+i*26,y:10};S.cur={x:50+i*26,y:50};up(null);
      }
      ok('最多三框',S.rects.length===3,'n'+S.rects.length);
      // 5) 线条框选：轨迹取外接矩形，标记为自定义框
      S.rects=[];S.activeBox=0;S.tool='line';
      S.action='line';S.linePts=[{x:100,y:100},{x:125,y:112},{x:145,y:140}];up(null);
      ok('线条框选',S.rects.length===1&&S.rects[0].kind==='line'&&S.rects[0].w===45,
         S.rects[0]?(S.rects[0].kind+' '+S.rects[0].w):'none');
      // 6) 删除当前框
      document.getElementById('toolDel').click();
      ok('删当前框',S.rects.length===0,'n'+S.rects.length);
      // 7) 三框同时修复
      S.mode='smart';S.iter=2;
      S.rects=[{x:100,y:100,w:40,h:30},{x:200,y:200,w:40,h:30},{x:300,y:300,w:40,h:30}];
      var multi=repair();ok('三框修复',multi.length>1000);
      // 8) 整图框（极端：无有效边界）
      S.rects=[{x:0,y:0,w:stage.width,h:stage.height}];S.activeBox=0;
      var u0=repair(); ok('整图框',u0.length>1000);
      // 9) 三模式
      var times=[];
      ['smart','average','texture'].forEach(function(m){
        S.mode=m;S.iter=2;S.rects=[{x:528,y:438,w:180,h:64}];S.activeBox=0;
        var s=performance.now();var u=repair();
        times.push(m+':'+Math.round(performance.now()-s)+'ms');
        ok('模式'+m,u.length>1000);
      });
      // 10) 三档力度 + 关闭锐化
      [1,2,3].forEach(function(it){S.mode='smart';S.iter=it;var u=repair();ok('力度'+it,u.length>1000)});
      S.sharpen=false;ok('关闭锐化',repair().length>1000);S.sharpen=true;
      S.mode='auto';S.iter=2;w('时间 '+times.join(' '));
      w('DONE');
    }catch(e){w('ERR '+e.message)}
  },50);
})();
</script>
'''


def main():
    html = open(HTML_PATH, encoding='utf-8').read()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w', encoding='utf-8').write(html.replace('</body>', TEST + '</body>'))
    print('已生成 ' + OUT)


if __name__ == '__main__':
    main()
