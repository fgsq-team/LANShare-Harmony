/**
 * 网页访问授权流程的自检。
 *
 * ## 为什么需要这个脚本
 * 真机现象：「浏览器访问网址提示『没有访问权限，请在手机上同意之后刷新页面』」。
 * 根因不是权限，而是**网页端与服务端的接口契约没对上**：
 *
 * | 接口 | 网页要什么（出处 js/lanshare.min.js） | 鸿蒙端早期给的是什么 |
 * |---|---|---|
 * | POST /initConfig | `{rootPath, name, token, pass}`（:195-198） | `{deviceName, udpPort, tcpPort, ...}` ❌ |
 * | POST /checkPass  | `{pass}`（:181） | `{ok}` ❌ |
 * | POST /updateWebName | 请求体 `{webName}`（:170） | 按 urlencoded 读 `name` ❌ |
 * | POST /files      | 响应 `{path, list:[{name,path,isDirectory,time}]}`（:376-400） | `{dir, count, items:[{isDir,size}]}` ❌ |
 *
 * `pass` 缺失 ⇒ 网页判定「没权限」⇒ 轮询 `/checkPass` 仍然拿不到 `pass`
 * ⇒ **永远进不去**。
 *
 * 本脚本做两件事：
 *   A. 直接执行交付的 `service/WebClientStore.ets`（Node 22 类型擦除），
 *      验证授权状态机：登记 → 待确认 → 放行 → 持久化往返。
 *   B. 静态断言服务端确实构造了网页所需的每一个键名，
 *      把「网页读什么」和「服务端给什么」钉在一起 —— 防止将来又被改回去。
 *
 * 用法：
 *   node --experimental-strip-types web_auth_check.mjs
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');
const ETS = path.join(ROOT, 'entry/src/main/ets');
const WEB = path.join(ROOT, 'entry/src/main/resources/rawfile/web');
const BUILD = path.join(__dirname, '_web_build');

// ------------------------------------------------------------------ shim
// 只替换平台绑定，不动任何业务逻辑。

const ARKDATA_SHIM = `
const __prefMem = new Map();
export const preferences = {
  async getPreferences(_ctx, _name) {
    return {
      async get(k, def) { return __prefMem.has(k) ? __prefMem.get(k) : def; },
      async put(k, v) { __prefMem.set(k, v); },
      async flush() {}
    };
  }
};
`;

const ABILITY_SHIM = `
export const common = {};
`;

const BASIC_SHIM = `
export class BusinessError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
`;

const HILOG_SHIM = `
export const hilog = { debug(){}, info(){}, warn(){}, error(){} };
`;

const SHIMS = [
  [/^\s*import\s*\{\s*preferences\s*\}\s*from\s*'@kit\.ArkData';\s*$/gm, ARKDATA_SHIM],
  [/^\s*import\s*\{\s*common\s*\}\s*from\s*'@kit\.AbilityKit';\s*$/gm, ABILITY_SHIM],
  [/^\s*import\s*\{\s*BusinessError\s*\}\s*from\s*'@kit\.BasicServicesKit';\s*$/gm, BASIC_SHIM],
  [/^\s*import\s*\{\s*hilog\s*\}\s*from\s*'@kit\.PerformanceAnalysisKit';\s*$/gm, HILOG_SHIM],
];

/**
 * 把 .ets 转成 Node 能跑的 .ts。
 * **保持目录结构**（core/、service/），这样源文件里的 `'../core/Logger'`
 * 加上 `.ts` 后仍然指向正确位置。
 */
function convert(rel) {
  let s = fs.readFileSync(path.join(ETS, rel), 'utf8');
  for (const [re, shim] of SHIMS) {
    s = s.replace(re, shim);
  }
  s = s.replace(/from\s*'(\.{1,2}\/[\w/]+)'/g, "from '$1.ts'");
  // 输出名要去掉 `.ets`，否则 import 里的 `../core/Logger.ts` 会找不到
  // （写成 core/Logger.ets.ts 就永远对不上）
  const out = path.join(BUILD, `${rel.replace(/\.ets$/, '')}.ts`);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, s, 'utf8');
  return pathToFileURL(out).href;
}

// ------------------------------------------------------------------ 断言
let pass = 0;
let fail = 0;
const failures = [];

function ok(name, cond, detail) {
  if (cond) {
    pass += 1;
    console.log(`  ✓ ${name}`);
  } else {
    fail += 1;
    failures.push(`${name}${detail ? ` — ${detail}` : ''}`);
    console.log(`  ✗ ${name}${detail ? `  << ${detail}` : ''}`);
  }
}

function eq(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  ok(name, a === e, a === e ? '' : `实际=${a} 期望=${e}`);
}

// ------------------------------------------------------------------ 主流程
console.log('=========================================================');
console.log(' 网页访问授权流程 — 自检');
console.log('=========================================================\n');

// ---- 载入交付源码 ----
const wsUrl = convert('service/WebClientStore.ets');
convert('core/Logger.ets');
convert('core/MiniJson.ets');

const { WebClientStore } = await import(wsUrl);
const { MiniJson } = await import(pathToFileURL(path.join(BUILD, 'core/MiniJson.ts')).href);

const fakeCtx = { filesDir: '/fake/files' };

// ==================================================================
console.log('【A】授权状态机（直接执行交付的 WebClientStore.ets）');
console.log('---------------------------------------------------------');

const s1 = new WebClientStore();
await s1.init(fakeCtx);
eq('A1 初始为空表', s1.count, 0);
eq('A2 初始无待确认', s1.pending().length, 0);

const bro = s1.add('192.168.10.186', '网页设备abc123', false);
ok('A3 token 为 32 位', bro.token.length === 32, `len=${bro.token.length}`);
ok('A4 token 为纯小写 hex', /^[0-9a-f]{32}$/.test(bro.token), bro.token);
eq('A5 新客户端默认未放行', bro.pass, false);

eq('A6 按 IP 能查到', s1.byIp('192.168.10.186')?.token, bro.token);
eq('A7 按 token 能查到', s1.byToken(bro.token)?.ip, '192.168.10.186');
eq('A8 未放行的进入待确认列表', s1.pending().length, 1);
eq('A9 未知 IP 查不到', s1.byIp('10.0.0.1'), null);
eq('A10 空 token 查不到', s1.byToken(''), null);

// 手机点「允许」
eq('A11 setPass 命中', s1.setPass(bro.token, true), true);
eq('A12 放行后待确认清空', s1.pending().length, 0);
eq('A13 放行状态生效', s1.byToken(bro.token)?.pass, true);
eq('A14 对不存在的 token setPass 返回 false', s1.setPass('deadbeef'.repeat(4), true), false);

// 第二个客户端（另一个 IP）
const phone = s1.add('192.168.10.200', '网页设备xyz789', false);
eq('A15 不同 IP 各自独立', s1.pending().length, 1);
eq('A16 总数 2', s1.count, 2);
eq('A17 改名', s1.updateName(phone.token, '我的笔记本电脑'), true);
eq('A18 改名后 custom=true', s1.byToken(phone.token)?.custom, true);
eq('A19 拒绝（移除）', s1.remove(phone.token), true);
eq('A20 移除后总数 1', s1.count, 1);

// 持久化
await s1.flush();

// ==================================================================
console.log('\n【B】持久化往返（模拟应用重启）');
console.log('---------------------------------------------------------');

const s2 = new WebClientStore();
await s2.init(fakeCtx);
eq('B1 重启后条数一致', s2.count, 1);
eq('B2 token 保留', s2.byToken(bro.token)?.token, bro.token);
eq('B3 ip 保留', s2.byToken(bro.token)?.ip, '192.168.10.186');
eq('B4 name 保留', s2.byToken(bro.token)?.name, '网页设备abc123');
eq('B5 pass 保留（已放行的不用重新确认）', s2.byToken(bro.token)?.pass, true);
ok('B6 createdMs 保留', (s2.byToken(bro.token)?.createdMs ?? 0) > 0);

// ==================================================================
console.log('\n【C】token 唯一性与格式（1000 次）');
console.log('---------------------------------------------------------');

const seen = new Set();
let allHex = true;
let allLen = true;
for (let i = 0; i < 1000; i++) {
  const t = WebClientStore.newToken ? WebClientStore.newToken() : null;
  if (t === null) break;
  seen.add(t);
  if (!/^[0-9a-f]{32}$/.test(t)) allHex = false;
  if (t.length !== 32) allLen = false;
}
if (seen.size === 0) {
  // newToken 是 private，通过 add 间接验证
  const probe = new WebClientStore();
  const set2 = new Set();
  for (let i = 0; i < 1000; i++) {
    set2.add(probe.add(`10.0.${Math.floor(i / 250)}.${i % 250}`, 'n', false).token);
  }
  eq('C1 token 唯一（1000 次无重复）', set2.size, 1000);
  ok('C2 全部 32 位纯 hex', [...set2].every((t) => /^[0-9a-f]{32}$/.test(t)));
} else {
  eq('C1 token 唯一（1000 次无重复）', seen.size, 1000);
  ok('C2 全部 32 位纯 hex', allHex && allLen);
}

// ==================================================================
console.log('\n【D】网页真实请求体的解析');
console.log('---------------------------------------------------------');

// /files 的请求体（lanshare.min.js:374）
const filesBody = '{"path":"\\/data\\/storage\\/el2\\/base\\/haps\\/entry\\/files\\/LANShare","isBack":false}';
const rf = MiniJson.parse(filesBody);
ok('D1 /files 请求体可解析', rf.ok);
eq('D2 取到 path', rf.root.field('path')?.asString(''), '/data/storage/el2/base/haps/entry/files/LANShare');
eq('D3 取到 isBack=false', rf.root.field('isBack')?.asBool(true), false);

// /updateWebName 的请求体（lanshare.min.js:170）
const nameBody = '{"webName":"我的笔记本电脑"}';
const rn = MiniJson.parse(nameBody);
ok('D4 /updateWebName 请求体可解析', rn.ok);
eq('D5 取到 webName（含中文）', rn.root.field('webName')?.asString(''), '我的笔记本电脑');

// 空 body（curl / 某些浏览器）
const re = MiniJson.parse('');
ok('D6 空 body 不抛异常、判为失败', !re.ok);

// ==================================================================
console.log('\n【E】网页 ↔ 服务端 键名一致性（静态断言）');
console.log('---------------------------------------------------------');

const routerSrc = fs.readFileSync(path.join(ETS, 'net/HttpRouter.ets'), 'utf8');

// 出处：js/lanshare.min.js:195-198
for (const key of ['rootPath', 'name', 'token', 'pass']) {
  ok(`E-initConfig 构造了 "${key}"`, routerSrc.includes(`"${key}":`), '网页读 a.' + key);
}
// 出处：js/lanshare.min.js:181
ok('E-checkPass 返回字段是 "pass"（不是 ok）',
  /"pass":\$\{pass \? 'true' : 'false'\}/.test(routerSrc));
// 出处：js/lanshare.min.js:376-400
for (const key of ['name', 'length', 'path', 'isFile', 'time', 'isDirectory']) {
  ok(`E-files 条目含 "${key}"`, routerSrc.includes(`\\"${key}\\":`) || routerSrc.includes(`"${key}":`));
}
// 出处：js/lanshare.min.js:170
ok('E-updateWebName 读的是 webName', routerSrc.includes("field('webName')"));

// 反向：网页确实在读这些（防止网页资源被换掉后断言失效）
const webJs = fs.readFileSync(path.join(WEB, 'js/lanshare.min.js'), 'utf8');
for (const probe of ['a.rootPath', 'a.token', 'a.pass', 'b.pass', 'd.isDirectory', 'e.isDirectory']) {
  ok(`E-网页侧确实读 "${probe}"`, webJs.includes(probe));
}
ok('E-网页侧发的是 webName', webJs.includes('JSON.stringify({webName: webName})'));
ok('E-网页侧 /files 用 isDirectory 渲染', webJs.includes('e.isDirectory'));

// 那条提示语必须还在（否则说明网页资源被替换，本脚本的前提变了）
ok('E-网页「没有访问权限」提示语存在',
  fs.readFileSync(path.join(WEB, 'lanshare.html'), 'utf8').includes('没有访问权限'));

// ==================================================================
console.log('\n=========================================================');
console.log(` 结果：${pass} 通过 / ${fail} 失败`);
if (fail > 0) {
  console.log('\n 失败项：');
  for (const f of failures) {
    console.log(`   - ${f}`);
  }
}
console.log('=========================================================');

process.exit(fail > 0 ? 1 : 0);
