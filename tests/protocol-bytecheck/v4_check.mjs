/**
 * v4 协议字节级对拍工具（Node 侧）—— 与 check.mjs 同一套方法论：
 * 不写 JS 镜像，而是**直接执行交付的 .ets 文件**，只做无歧义的平台绑定替换。
 *
 * 覆盖三块 v4 新增的纯逻辑：
 *   core/MiniJson.ets    解析对端 fastjson 产出的 JSON
 *   core/FileCrypto.ets  文件体逐字节变换（mUtil.encData/decData）
 *   net/ProtoIO.ets      v4 裸序列化（int / long / string / bool / join）
 *
 * ## 输出契约（关键）
 * 本脚本除了给出**实测结果**，还一并吐出**用例输入原文**（jsonCases / quoteCases /
 * fileCrypto.sampleHex / proto.ints ...）。Python 侧据此独立重算期望值，
 * 这样「用例清单」只有一份，两侧不会各写一份而悄悄漂移。
 *
 * 用法：node v4_check.mjs      → stdout 输出 JSON，由 v4_compare.py 对拍
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../../');
const ETS = path.join(ROOT, 'entry/src/main/ets');
const BUILD = path.join(__dirname, '_v4build');

/** ArkTS util 的适配层（同 check.mjs，TextEncoder/Decoder 语义等价） */
const ARK_UTIL_SHIM = `
const ArkUtil = {
  TextEncoder: class {
    encodeInto(s) { return new TextEncoder().encode(s); }
  },
  TextDecoder: {
    create(_e) { return { decodeToString: (u) => new TextDecoder('utf-8').decode(u) }; }
  }
};
`;

/**
 * TcpChannel 的桩。
 * ProtoIO 只用到它的 readExactly 做异步读，而本次测的是**纯字节构造**部分，
 * 所以给个桩即可，不需要真的建立连接。
 */
const TCP_CHANNEL_STUB = `
class TcpChannel {
  async readExactly(_n, _t) { return new Uint8Array(0); }
}
`;

function convert(rel, outName) {
  let s = fs.readFileSync(path.join(ETS, rel), 'utf8');
  s = s.replace(/^\s*import\s*\{\s*util\s*\}\s*from\s*'@kit\.ArkTS';\s*$/gm, ARK_UTIL_SHIM);
  s = s.replace(/\butil\.TextEncoder\b/g, 'ArkUtil.TextEncoder');
  s = s.replace(/\butil\.TextDecoder\b/g, 'ArkUtil.TextDecoder');
  // ProtoIO 里的 TcpChannel 换成桩（只影响异步读方法，不影响被测的字节构造）
  s = s.replace(/^\s*import\s*\{\s*TcpChannel\s*\}\s*from\s*'\.\/NativeSocket';\s*$/gm, TCP_CHANNEL_STUB);
  // 相对导入补 .ts
  s = s.replace(/from\s*'(\.{1,2}\/[\w/]+)'/g, "from '$1.ts'");
  const out = path.join(BUILD, `${outName}.ts`);
  fs.writeFileSync(out, s, 'utf8');
  return pathToFileURL(out).href;
}

fs.mkdirSync(BUILD, { recursive: true });
const miniJsonUrl = convert('core/MiniJson.ets', 'MiniJson');
const fileCryptoUrl = convert('core/FileCrypto.ets', 'FileCrypto');
const protoIoUrl = convert('net/ProtoIO.ets', 'ProtoIO');

const { MiniJson, JsonNode } = await import(miniJsonUrl);
const { FileCrypto } = await import(fileCryptoUrl);
const { ProtoIO } = await import(protoIoUrl);

const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join('');

// ---------------------------------------------------------------- JSON 用例
// 全部来自真实场景：fastjson 产出的设备 JSON、文件清单 JSON，
// 以及各种转义 / 中文 / 大整数 / 嵌套 / 空值 / 重复键。
const JSON_CASES = [
  '{"a":1,"b":"x"}',
  '{"name":"中文名字.jpg","length":1234567890123,"fileType":5}',
  '{"s":"a\\"b\\\\c\\nd","u":"\\u4e2d"}',
  '{"x":true,"y":false,"z":null}',
  '{"devName":"我的小米手机","devIP":"192.168.10.100","devNetMask":"255.255.255.0",' +
    '"devBrotIP":"192.168.10.255","uniqueUUid":"abc-123","devPort":5856,"devMode":1,' +
    '"dataVersion":4,"isIPv4":true,"batteryLevel":87,"chargeStatus":-1}',
  '{"fromDevice":{"devName":"Sender","devIP":"10.0.0.2"},"type":0,"groupId":0,' +
    '"files":[{"fileId":"f1","name":"a.png","length":2048,"fileType":1,"toUser":"Target"' +
    ',"video":false,"videoTime":"","gif":false}]}',
  '  {  "spaced"  :  [ 1 , 2 , { "deep" : [ true , null ] } ]  }  ',
  '{"p":99.5,"q":-0.25,"big":9007199254740991}',
  '{"n":-2}',
  '{}',
  '[]',
  '{"empty":"","arr":[]}',
  '{"folder":{"name":"资料","fileType":6,"fileCount":1,"children":[' +
    '{"fileId":"c1","name":"b.docx","length":10,"fileType":5}]}}',
  '{"unicode":"\\u4e2d\\u6587\\u6d4b\\u8bd5","tab":"a\\tb","slash":"a\\/b"}',
  '{"a":1,"a":2}',                 // 重复键：fastjson / Python 都是「后者胜」
  ' {"a":1} \n\t ',                // 首尾空白必须容忍（长度前缀读出来的串可能带 \n）
  '{"e":1e3,"f":-2.5E-2}',         // 指数写法
];

/** 必须解析失败：解析器不许「拿着半对的 Object 继续跑」 */
const JSON_BAD = [
  ['unclosed', '{"a":1'],
  ['brace-trailing', '{"a":1}}'],
  ['two-objects', '{} {}'],
  ['word-truncated', 'tru'],
  ['non-number', '{"a":xyz}'],
  ['bad-escape', '{"a":"\\x"}'],
  ['empty', ''],
  ['bare-comma', '{"a":1,}'],
];

/** 已固化的预期值（标准 JSON 推不出来，属于本实现的**有意**设计） */
const JSON_GUARD = [
  // MAX_DEPTH = 64：70 层嵌套必须被拒绝，防栈溢出。
  // Python 标准库能解析它 —— 这是有意分歧，不是 bug。
  ['depth-guard', '['.repeat(70) + ']'.repeat(70), 'FAIL_OK'],
];

/** JsonNode -> 普通 JS 值（键排序后由 JSON.stringify 输出，确保与 Python 侧可比） */
function toPlain(n) {
  switch (n.kind) {
    case JsonNode.T_NULL: return null;
    case JsonNode.T_BOOL: return n.asBool(false);
    case JsonNode.T_NUM: return n.asNumber(0);
    case JsonNode.T_STR: return n.asString('');
    case JsonNode.T_ARR: {
      const out = [];
      for (let i = 0; i < n.count; i++) out.push(toPlain(n.at(i)));
      return out;
    }
    default: {
      const out = {};
      const ks = n.keys().sort();
      for (const k of ks) out[k] = toPlain(n.field(k));
      return out;
    }
  }
}

const results = {};

// ---- JSON 解析 ----
for (let i = 0; i < JSON_CASES.length; i++) {
  const r = MiniJson.parse(JSON_CASES[i]);
  results[`json:${i}`] = r.ok ? JSON.stringify(toPlain(r.root)) : `PARSE_ERROR ${r.error}`;
}

for (const [name, src] of JSON_BAD) {
  results[`jsonbad:${name}`] = MiniJson.parse(src).ok ? 'WRONGLY_OK' : 'FAIL_OK';
}

for (const [name, src, expected] of JSON_GUARD) {
  const ok = MiniJson.parse(src).ok;
  const got = ok ? 'WRONGLY_OK' : 'FAIL_OK';
  results[`jsonguard:${name}`] = got === expected ? got : `${got} (预期 ${expected})`;
}

// ---- JSON 生成（MiniJson.quote） ----
const QUOTE_CASES = [
  'plain',
  'a"b',
  'a\\b',
  'line1\nline2',
  'tab\there',
  '\u0001\u001f',
  '\b\f\r',
  '中文/路径\\文件',
  '',
];
for (let i = 0; i < QUOTE_CASES.length; i++) {
  results[`quote:${i}`] = MiniJson.quote(QUOTE_CASES[i]);
}

// ---- FileCrypto ----
const SAMPLE = new Uint8Array(300);
for (let i = 0; i < SAMPLE.length; i++) SAMPLE[i] = (i * 7 + 3) & 0xFF;
const IDX = [0, 1, 255, 256, 4096, 1000000];

for (const idx of IDX) {
  const buf = SAMPLE.slice();
  FileCrypto.encData(buf, SAMPLE.length, 0, idx);
  results[`enc:${idx}`] = hex(buf);
  const back = buf.slice();
  FileCrypto.decData(back, SAMPLE.length, 0, idx);
  results[`decRound:${idx}`] = hex(back) === hex(SAMPLE) ? 'OK' : 'MISMATCH';
}

// 256 个单字节值的往返双射（把整个字节域穷举一遍）
{
  let bad = '';
  for (let i = 0; i < 256 && bad === ''; i++) {
    const one = new Uint8Array([i]);
    FileCrypto.encData(one, 1, 0, 12345);
    FileCrypto.decData(one, 1, 0, 12345);
    if (one[0] !== i) bad = `0x${i.toString(16)} -> 0x${one[0].toString(16)}`;
  }
  results['filecrypto:roundtrip256'] = bad === '' ? 'OK' : `FAIL ${bad}`;
}

// 分片语义：拆 3 段（index 累计）必须等于整段
{
  const whole = SAMPLE.slice();
  FileCrypto.encData(whole, 300, 0, 0);
  const parts = SAMPLE.slice();
  FileCrypto.encData(parts, 100, 0, 0);
  FileCrypto.encData(parts, 100, 100, 100);
  FileCrypto.encData(parts, 100, 200, 200);
  results['filecrypto:chunked-equals-whole'] = hex(whole) === hex(parts) ? 'OK' : 'MISMATCH';
}

// 非零 off + 非零 index 的组合（越界必须安全截断，不许抛）
{
  const buf = SAMPLE.slice();
  FileCrypto.encData(buf, 100, 250, 250);   // 250+100 > 300 → 只处理 50 字节
  results['filecrypto:off-len-clamped'] = hex(buf.slice(250, 300));
}

// ---- ProtoIO ----
const P_INTS = [0, 1, -1, -2, 1101, 1102, 5856, 2147483647, -2147483648];
const P_LONGS = [0, 1, 1735689600000, 4294967296, 9007199254740991];
const P_STRS = ['', 'a', 'abc', '中文设备名', 'a"b\\c'];

for (const v of P_INTS) {
  results[`proto:int:${v}`] = hex(ProtoIO.intBytes(v));
  results[`proto:beInt:${v}`] = String(ProtoIO.beInt(ProtoIO.intBytes(v)));
}
for (const v of P_LONGS) {
  results[`proto:long:${v}`] = hex(ProtoIO.longBytes(v));
}
for (const s of P_STRS) {
  results[`proto:str:${s}`] = hex(ProtoIO.stringBytes(s));
}
results['proto:str:null'] = hex(ProtoIO.stringBytes(null));
results['proto:bool:true'] = hex(ProtoIO.boolBytes(true));
results['proto:bool:false'] = hex(ProtoIO.boolBytes(false));
results['proto:byte:0x8f'] = hex(ProtoIO.byteBytes(0x8F));

// join 必须严格按顺序拼接 —— 这条正是 v4 建链后首包的真实形状
results['proto:join'] = hex(ProtoIO.join([
  ProtoIO.intBytes(-2),
  ProtoIO.stringBytes('dev'),
  ProtoIO.intBytes(1101),
  ProtoIO.boolBytes(false),
  ProtoIO.stringBytes('{"files":[]}')
]));

process.stdout.write(JSON.stringify({
  jsonCases: JSON_CASES,
  jsonBad: JSON_BAD,
  jsonGuard: JSON_GUARD,
  quoteCases: QUOTE_CASES,
  fileCrypto: { sampleHex: hex(SAMPLE), indices: IDX },
  proto: { ints: P_INTS, longs: P_LONGS, strings: P_STRS },
  results
}));
