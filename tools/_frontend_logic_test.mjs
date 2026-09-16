// 前端自动填入逻辑的单元测试（Node，无浏览器）。
// 直接加载 templates/index.html 里真实的 <script>，替换 DOM/fetch 环境后驱动状态机。
import {readFileSync, writeFileSync} from "node:fs";

// ── 极简 DOM 桩 ──
class El {
  constructor(tag, dataset = {}) {
    this.tagName = tag;
    this.dataset = dataset;
    this.value = "";
    this.hidden = false;
    this.textContent = "";
    this.innerHTML = "";
    this.className = "";
    this.children = [];
    this.listeners = {};
    this.checked = true;
    this.disabled = false;
    this.style = {};
    this._cls = new Set();
    const self = this;
    this.classList = {
      add: (...c) => c.forEach((x) => self._cls.add(x)),
      remove: (...c) => c.forEach((x) => self._cls.delete(x)),
      toggle: (c, f) => {
        const on = f === undefined ? !self._cls.has(c) : Boolean(f);
        if (on) self._cls.add(c); else self._cls.delete(c);
        return on;
      },
      contains: (c) => self._cls.has(c),
    };
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute() {}
  getAttribute() { return null; }
  removeAttribute() {}
  focus() {}
  querySelector() { return new El("div"); }
  querySelectorAll() { return []; }
}

const bySelector = new Map();
const make = (sel) => {
  if (!bySelector.has(sel)) bySelector.set(sel, new El("div"));
  return bySelector.get(sel);
};

const globalDocument = {
  activeElement: null,
  hidden: false,
  addEventListener() {},
  querySelector: (sel) => make(sel),
  querySelectorAll: (sel) => {
    if (sel === "[data-role]") {
      return [make("adc-btn"), make("sup-btn")].map((el, i) => {
        el.dataset.role = i === 0 ? "adc" : "support";
        return el;
      });
    }
    return [];
  },
  createElement: (tag) => new El(tag),
};

// fetch 桩：按 URL 返回固定数据；/api/lcu/state 永远挂起（测试直接调 applyLcuPayload）
const stateQueue = [];
globalThis.fetch = async (url, init) => {
  if (url === "/api/lcu/state") {
    return new Promise(() => {}); // 挂起
  }
  if (url === "/api/champions") {
    return {json: async () => ({bottom: [], support: [], data_meta: {update_time: "test"}})};
  }
  if (url === "/api/mylists") {
    return {json: async () => ({
      ok: true,
      lists: {
        adc_block: {champions: []}, adc_fav: {champions: []},
        support_block: {champions: []}, support_fav: {champions: []},
      },
    })};
  }
  if (String(url).startsWith("/api/recommend")) {
    return {json: async () => ({results: [], state_info: {}, summary: {}, excluded_champions: []})};
  }
  if (String(url).startsWith("/api/lcu/config")) {
    return {json: async () => ({ok: true, enabled: JSON.parse(init.body).enabled})};
  }
  return {json: async () => ({})};
};

// 定时器桩：不真正跑，避免 Node 进程挂着
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {};
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};

// ── 加载真实脚本 ──
const html = readFileSync(new URL("../templates/index.html", import.meta.url), "utf-8");
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const exportShim = `
;globalThis.__t = {
  applyLcuPayload, applyLcuFills, clearLcuFills, detachLcuFills, setRole, pollLcu, lcuState,
  get inputs() { return inputs; },
  get lcuTags() { return lcuTags; },
  get role() { return role; },
  get roleButtons() { return roleButtons; },
  get clearButton() { return clearButton; },
  get lcuAuto() { return lcuAuto; },
};
`;
const code = "(function(){\nconst document = globalThis.__document;\n"
  + script
  + "\n" + exportShim + "\n})()";

globalThis.__document = globalDocument;
// 用 Function 执行，让 const 声明落在函数作用域内（由 shim 暴露引用）
new Function("globalThis", code)(globalThis);

const t = globalThis.__t;

// ── 造数 ──
const CH = (id, cn) => ({id, cn_name: cn, name: id, avatar: "", tier: "S"});
function payload({inSelect = true, enabled = true, roleHint = "support", allyAdc = CH("jinx", "暴走萝莉"), allySup = CH("lulu", "仙灵女巫"),
                    enemyAdc = CH("caitlyn", "皮城女警"), enemySup = CH("morgana", "堕落天使"),
                    confAdc = "high", confSup = "high"} = {}) {
  return {
    ok: true, enabled, running: true, connected: true, source: "lockfile:test", error: null,
    in_champ_select: inSelect, revision: 1, last_poll: "12:00:00",
    queue: inSelect ? {id: 420, name: "单双排位"} : null,
    phase: "BAN_PICK",
    timer: {phase: "BAN_PICK", total_sec: 30, remaining_sec: 21},
    my_position: roleHint || "",
    role_hint: roleHint || null,
    ally: {adc: allyAdc, support: allySup},
    enemy: {
      adc: {champion: enemyAdc, confidence: confAdc, inferred: true},
      support: {champion: enemySup, confidence: confSup, inferred: true},
    },
    bans: {ally: [], enemy: []},
    enemy_pick_count: 2,
  };
}

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log("  PASS", name); }
  else { fail++; console.log("  FAIL", name, detail === undefined ? "" : "← " + JSON.stringify(detail)); }
}
const val = (id) => t.inputs[id].value;
const tag = (id) => (t.lcuTags[id].hidden ? null : t.lcuTags[id].className + ":" + t.lcuTags[id].textContent);

// 等初始化的微任务链跑完
for (let i = 0; i < 10; i++) await Promise.resolve();
await new Promise((r) => process.nextTick(r));

console.log("== 1) 进入选人：自动填入 + 切分路 ==");
t.applyLcuPayload(payload({roleHint: "adc"}));
check("ally_ad 填入", val("ally_ad") === "暴走萝莉 (jinx)", val("ally_ad"));
check("ally_sup 填入", val("ally_sup") === "仙灵女巫 (lulu)", val("ally_sup"));
check("enemy_ad 填入", val("enemy_ad") === "皮城女警 (caitlyn)", val("enemy_ad"));
check("enemy_sup 填入", val("enemy_sup") === "堕落天使 (morgana)", val("enemy_sup"));
check("分路自动切到 adc", t.role === "adc", t.role);
check("enemy 标签=自动", tag("enemy_ad") === "auto-tag:自动", tag("enemy_ad"));
check("lcu-filled 样式", t.inputs.enemy_ad.classList.contains("lcu-filled"));

console.log("== 2) 低可信度：标签降级 ==");
t.applyLcuPayload(payload({roleHint: "adc", enemyAdc: CH("swain", "诺克萨斯统领"), confAdc: "low"}));
check("enemy_ad=存疑", tag("enemy_ad") === "auto-tag is-unsure:存疑", tag("enemy_ad"));
check("enemy_ad 值更新", val("enemy_ad") === "诺克萨斯统领 (swain)", val("enemy_ad"));

console.log("== 3) 用户手动改框：不被覆盖，标手动 ==");
t.inputs.enemy_ad.value = "寒冰射手 (ashe)"; // 模拟用户输入
t.applyLcuPayload(payload({roleHint: "adc", enemyAdc: CH("swain", "诺克萨斯统领"), confAdc: "low"}));
check("手动值保留", val("enemy_ad") === "寒冰射手 (ashe)", val("enemy_ad"));
check("标签=手动", tag("enemy_ad") === "auto-tag is-manual:手动", tag("enemy_ad"));
console.log("== 4) 客户端来了新信息：重新接管 ==");
t.applyLcuPayload(payload({roleHint: "adc", enemyAdc: CH("ezreal", "探险家"), confAdc: "high"}));
check("新值覆盖手动值", val("enemy_ad") === "探险家 (ezreal)", val("enemy_ad"));
check("标签恢复自动", tag("enemy_ad") === "auto-tag:自动", tag("enemy_ad"));

console.log("== 5) 退出选人：自动清空 ==");
t.applyLcuPayload(payload({inSelect: false}));
check("ally_ad 清空", val("ally_ad") === "", val("ally_ad"));
check("enemy_ad 清空", val("enemy_ad") === "", val("enemy_ad"));
check("标签隐藏", tag("enemy_ad") === null, tag("enemy_ad"));

console.log("== 6) 再进入新一局：重新填入 ==");
t.inputs.enemy_ad.value = "探险家 (ezreal)"; // 模拟上一局残留
t.applyLcuPayload(payload({roleHint: "support", enemyAdc: CH("kaisa", "虚空之女"), confAdc: "high"}));
check("残留被清掉换新局", val("enemy_ad") === "虚空之女 (kaisa)", val("enemy_ad"));
check("分路切回 support", t.role === "support", t.role);

console.log("== 7) 用户手动切分路：roleOverride ==");
t.applyLcuPayload(payload({roleHint: "adc"}));
check("先跟客户端切到 adc", t.role === "adc", t.role);
const adcBtn = t.roleButtons.find((b) => b.dataset.role === "adc");
adcBtn.listeners.click[0](); // 用户点 ADC（已激活）
check("仍为 adc", t.role === "adc", t.role);
const supBtn = t.roleButtons.find((b) => b.dataset.role === "support");
supBtn.listeners.click[0](); // 用户手动切回辅助
check("用户切到 support", t.role === "support", t.role);
t.applyLcuPayload(payload({roleHint: "adc"}));
check("客户端不再覆盖手动分路", t.role === "support", t.role);
t.applyLcuPayload(payload({inSelect: false}));
t.applyLcuPayload(payload({roleHint: "adc"}));
check("新一局恢复自动切", t.role === "adc", t.role);

console.log("== 8) 正在编辑的框不动 ==");
globalDocument.activeElement = t.inputs.ally_sup;
t.applyLcuPayload(payload({roleHint: "adc", allySup: CH("janna", "风暴之怒")}));
check("编辑中的框不被写", val("ally_sup") === "仙灵女巫 (lulu)", val("ally_sup"));
globalDocument.activeElement = null;
t.applyLcuPayload(payload({roleHint: "adc", allySup: CH("janna", "风暴之怒")}));
check("失焦后恢复接管", val("ally_sup") === "风暴之怒 (janna)", val("ally_sup"));

console.log("== 9) 清空按钮：本轮不再自动回填 ==");
const p9 = payload({roleHint: "adc", allySup: CH("janna", "风暴之怒")});
t.applyLcuPayload(p9); // 让 desired 稳定在这份数据上
t.clearButton.listeners.click[0]();
check("全部清空", ["ally_ad", "ally_sup", "enemy_ad", "enemy_sup"].every((i) => val(i) === ""));
t.applyLcuPayload(JSON.parse(JSON.stringify(p9))); // 相同数据再推一次
check("清空后不被立即回填", ["ally_ad", "ally_sup", "enemy_ad", "enemy_sup"].every((i) => val(i) === ""));
t.applyLcuPayload(payload({roleHint: "adc", allySup: CH("janna", "风暴之怒"), enemySup: CH("leona", "曙光女神")}));
check("客户端有新信息才回填", val("enemy_sup") === "曙光女神 (leona)", val("enemy_sup"));

console.log("== 10) 关闭自动识别：值保留、不再接管 ==");
t.lcuAuto.checked = false;
await t.lcuAuto.listeners.change[0]();
check("输入框值保留", val("enemy_sup") === "曙光女神 (leona)", val("enemy_sup"));
check("标签隐藏", tag("enemy_sup") === null, tag("enemy_sup"));
const before = val("enemy_ad");
t.applyLcuPayload(payload({enabled: false, roleHint: "adc", enemyAdc: CH("vayne", "暗夜猎手")}));
check("关闭后不再写入", val("enemy_ad") === before, val("enemy_ad"));

console.log("");
console.log("通过 " + pass + " / " + (pass + fail));
process.exit(fail ? 1 : 0);
