# -*- coding: utf-8 -*-
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(_sys.argv[0])))
"""调试：探测认证页 Shadow DOM 结构（open/closed、输入框藏在哪），不提交表单"""
import json
import time

from common import load_config, log, make_driver

PROBE_JS = r"""
var root = document.querySelector('app-pc-authenticate');
var info = {rootFound: !!root, rootShadow: null, deepInputs: [], closed: 0, open: 0, total: 0};

// 统计全页面所有自定义元素的 shadowRoot 情况
var all = document.querySelectorAll('*');
info.total = all.length;
for (var i = 0; i < all.length; i++) {
  var el = all[i];
  if (el.shadowRoot) { info.open++; }
  // 试图用 element.openShadow 兜底拿 closed root 不可能，但能数出有多少组件可能有 shadow
  if (el.tagName.indexOf('-') > -1) { info.hasHybrid = true; }
}
if (root && root.shadowRoot) {
  info.rootShadow = 'open';
  var inputs = root.shadowRoot.querySelectorAll('input');
  for (var j = 0; j < inputs.length; j++) {
    info.deepInputs.push({tag: inputs[j].tagName, type: inputs[j].type,
                          ph: inputs[j].placeholder || '', id: inputs[j].id});
  }
}
// 直接深度遍历找 input（与 main.py 相同逻辑）
function walk(r, out) {
  var els = r.querySelectorAll('*');
  for (var i = 0; i < els.length; i++) {
    var el = els[i];
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      out.push({tag: el.tagName, type: el.type, ph: el.placeholder || '',
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                inShadow: false, path: ''});
    }
    if (el.shadowRoot) {
      var sins = el.shadowRoot.querySelectorAll('input, textarea');
      for (var k = 0; k < sins.length; k++) {
        out.push({tag: sins[k].tagName, type: sins[k].type, ph: sins[k].placeholder || '',
                  visible: !!(sins[k].offsetWidth || sins[k].offsetHeight || sins[k].getClientRects().length),
                  inShadow: true, host: el.tagName});
      }
    }
  }
}
var out = [];
walk(document, out);
info.walkResult = out;
return info;
"""

cfg = load_config()
driver = None
try:
    driver = make_driver(headless=False)
    log("打开认证页: %s" % cfg["url"])
    driver.get(cfg["url"])
    time.sleep(8)  # 给足渲染时间
    info = driver.execute_script(PROBE_JS)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    driver.save_screenshot("logs/debug_shadow.png")
    log("调试完成")
finally:
    if driver:
        driver.quit()
