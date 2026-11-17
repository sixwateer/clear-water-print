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
      S.rects=[{x:stage.width-60,y:stage.height-30,w:60,h:30}];
      var e=null,d=null;
      try{d=localDetect(S.rects[0])}catch(err){e=err.message}
      ok('贴边识别',!e,e||(d.label+'/'+d.mode));
      // 2) 自动框右下角
      document.getElementById('toolAuto').click();
      ok('自动框',S.rects.length===1,'x'+Math.round(S.rects[0].x));
      // 3) 方向键微调
      var bx=S.rects[0].x;
      window.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft'}));
      ok('方向键微调',Math.abs(S.rects[0].x-(bx-1))<0.001,(bx-1)+'->'+S.rects[0].x);
      // 4) 整图框（极端：无有效边界）
      S.rects=[{x:0,y:0,w:stage.width,h:stage.height}];
      var u0=repair(); ok('整图框',u0.length>1000);
      // 5) 三模式
      var times=[];
      ['smart','average','texture'].forEach(function(m){
        S.mode=m;S.iter=2;S.rects=[{x:528,y:438,w:180,h:64}];
        var s=performance.now();var u=repair();
        times.push(m+':'+Math.round(performance.now()-s)+'ms');
        ok('模式'+m,u.length>1000);
      });
      // 6) 三档力度 + 关闭锐化
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
