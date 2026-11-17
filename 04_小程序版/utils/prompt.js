/**
 * 提示词意图解析（纯本地，无网络请求）
 *
 * 提示词在这里不是"发给 AI 的咒语"，而是用来明确两件事：
 *   1) 目标是什么（框住的哪个东西）
 *   2) 框内空白按什么补全（背景色 / 衣物纹理 / 边缘平均色）
 * 解析结果映射到一个修复框架，由 inpaint.js 执行；框外像素始终不变。
 */

var EXAMPLE = '我要去掉的是框住的蓝色包（包蓝蓝.png 中人物的包），其余区域依据背景或人物衣物进行修改。';

// 补全依据 → 框架。顺序即优先级：纹理最难，优先命中后不被"背景"覆盖。
var RULES = [
  { re: /纹理|衣物|衣服|衣料|布料|条纹|木纹|草地|毛发|织物|褶皱/, fill: '衣物/背景纹理', framework: 'texture' },
  { re: /渐变|纯色|单色|天空|白墙|干净背景/, fill: '周围背景渐变', framework: 'smart' },
  { re: /背景|墙面|地面|周围/, fill: '周围背景', framework: 'smart' },
  { re: /快速|平均|取色|小面积|纯色块/, fill: '边缘平均色', framework: 'average' }
];

var FRAMEWORK_LABEL = {
  smart: '智能扩散',
  texture: '纹理重建',
  average: '快速填充'
};

/** 提取目标描述：优先取「框住的/要去掉的」之后的短语 */
function pickTarget(text) {
  // 「框住的 XX」优先于「要去掉的 XX」：前者更精确，后者常带"是框住的"等前缀
  var patterns = [
    /(?:框住|框选|圈住|选中)的?([^，,。；;（）()]{1,24})/,
    /(?:要去掉|要去除|要擦除|去掉|去除)的?([^，,。；;（）()]{1,24})/
  ];
  for (var i = 0; i < patterns.length; i++) {
    var m = text.match(patterns[i]);
    if (!m) continue;
    return m[1]
      .replace(/^(?:是|的|那个|这个)+/, '')
      .replace(/^(?:框住|框选|圈住|选中)的?/, '')
      .trim();
  }
  return '';
}

/**
 * @param {String} text 用户提示词
 * @returns {Object} { raw, target, fill, framework, intent, matched }
 */
function parsePrompt(text) {
  var s = String(text || '').trim();
  var out = { raw: s, target: '', fill: '', framework: '', intent: '', matched: [] };
  if (!s) return out;

  out.target = pickTarget(s);
  for (var i = 0; i < RULES.length; i++) {
    if (RULES[i].re.test(s)) {
      out.fill = RULES[i].fill;
      out.framework = RULES[i].framework;
      out.matched.push(RULES[i].fill);
      break;
    }
  }
  // 尚未命中补全依据时，保留当前用户所选框架，不擅自改写
  var parts = [];
  if (out.target) parts.push('目标：' + out.target);
  if (out.fill) parts.push('按' + out.fill + '补全');
  if (out.framework) parts.push('推荐「' + FRAMEWORK_LABEL[out.framework] + '」');
  out.intent = parts.length ? parts.join(' · ') : '已记录提示词，未识别到明确目标或补全依据';
  return out;
}

module.exports = { parsePrompt: parsePrompt, EXAMPLE: EXAMPLE, FRAMEWORK_LABEL: FRAMEWORK_LABEL };
