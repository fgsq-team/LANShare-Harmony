/**
 * 协议字节级对拍工具（Node 侧）
 *
 * ## 目的
 * 证明 HarmonyOS 端 DataPacket.ets 与 Android 端 DataEnc.java/DataDec.java
 * 产出**位级一致**的字节流。
 *
 * ## 做法
 * 不手写一份 JS 镜像 —— 手镜像会引入「两份代码同时写错」的风险。
 * 而是直接从**交付文件本身**取证：
 *   1. 读取真实的 entry/src/main/ets/core/{ByteCodec,DataPacket,LanConfig}.ets
 *   2. 只做 3 处无歧义的替换，落到 _build/*.ts
 *        - 删掉 `@kit.ArkTS` 的导入，把 util.TextEncoder/TextDecoder
 *          换成平台内置同名类（语义等价）
 *        - 相对导入补 .ts 后缀（Node ESM 要求显式扩展名）
 *   3. 交给 Node 22 原生的 TypeScript 类型擦除（--experimental-strip-types）
 *      执行。类型信息只是编译期注解，擦除后即为 ArkTS 的真实运行语义。
 *
 * 之所以不用正则自己擦类型：三元表达式的 `:` 和类型注解的 `:` 形态相同，
 * 正则无法区分（实测会吃掉 `a ? b : c` 里的 `: c`）。
 *
 * 用法：
 *   node tests/protocol-bytecheck/check.mjs
 * 退出码 0 = 正常产出（对拍由 compare.py 负责）
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../../');
const SRC = path.join(ROOT, 'entry/src/main/ets/core');
const BUILD = path.join(__dirname, '_build');

/**
 * ArkTS 平台模块 shim。
 *
 * ArkTS 的 util.TextEncoder/TextDecoder 与 Web 同名 API **签名不同**：
 *   ArkTS: new util.TextEncoder().encodeInto(str) -> Uint8Array
 *          util.TextDecoder.create('utf-8').decodeToString(u8) -> string
 *   Web  : new TextEncoder().encode(str)
 *          new TextDecoder().decode(u8)
 * 这里提供 ArkTS 形状的适配层，让被测的 .ets 逻辑原封不动跑起来。
 */
const ARK_UTIL_SHIM = `
const ArkUtil = {
  TextEncoder: class {
    encodeInto(s: string): Uint8Array {
      return new TextEncoder().encode(s);
    }
  },
  TextDecoder: {
    create(_encoding: string): { decodeToString: (u: Uint8Array) => string } {
      return { decodeToString: (u: Uint8Array): string => new TextDecoder('utf-8').decode(u) };
    }
  }
};
`;

/** 把 .ets 转成 Node 可直接执行的 .ts —— 只改平台绑定，不动任何逻辑 */
function convert(name) {
  let s = fs.readFileSync(path.join(SRC, `${name}.ets`), 'utf8');

  // 1) ArkTS 平台模块导入 -> 换成 shim（TextEncoder/TextDecoder 语义一致）
  s = s.replace(
    /^\s*import\s*\{\s*util\s*\}\s*from\s*'@kit\.ArkTS';\s*$/gm,
    ARK_UTIL_SHIM
  );
  s = s.replace(/\butil\.TextEncoder\b/g, 'ArkUtil.TextEncoder');
  s = s.replace(/\butil\.TextDecoder\b/g, 'ArkUtil.TextDecoder');

  // 2) 相对导入补 .ts 后缀（Node ESM 要求显式扩展名）
  s = s.replace(/from\s*'(\.\/[\w]+)'/g, "from '$1.ts'");

  const out = path.join(BUILD, `${name}.ts`);
  fs.writeFileSync(out, s, 'utf8');
  return out;
}

fs.mkdirSync(BUILD, { recursive: true });
convert('LanConfig');
convert('ByteCodec');
convert('DataPacket');

// Windows 上动态 import 必须用 file:// URL，不能直接给盘符路径
const mod = await import(pathToFileURL(path.join(BUILD, 'DataPacket.ts')).href);
const codecMod = await import(pathToFileURL(path.join(BUILD, 'ByteCodec.ts')).href);
const cfgMod = await import(pathToFileURL(path.join(BUILD, 'LanConfig.ts')).href);
const { DataEnc, DataDec, DataPacket } = mod;
const { ByteWriter, ByteReader } = codecMod;
const { LanConfig } = cfgMod;

// ---------------------------------------------------------------- 用例集

const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join('');

function buildCases() {
  const cases = [];

  cases.push({
    name: 'udpEmpty(UDP_GET_DEVICES)',
    bytes: (() => {
      const e = new DataEnc(0);
      e.packData(1001);
      return e.encodeUdp();
    })()
  });

  cases.push({
    name: 'udpString(UDP_SET_DEVICES, 中文设备名)',
    bytes: (() => {
      const e = new DataEnc(64);
      e.packData(1002);
      e.putString('我的小米手机-中文');
      return e.encodeUdp();
    })()
  });

  cases.push({
    name: 'mixed fields',
    bytes: (() => {
      const e = new DataEnc(128);
      e.packData(1105);
      e.setCount(7);
      e.putByte(0x41);
      e.putBoolean(true);
      e.putBoolean(false);
      e.putShort(0xBEEF);
      e.putInt(-123456789);
      e.putLong(1735689600000);
      e.putString('hello world');
      e.putString('');
      e.putBytes(new Uint8Array([0, 1, 127, 128, 254, 255]));
      return e.encode();
    })()
  });

  cases.push({
    name: 'payload all 0xFF',
    bytes: (() => {
      const e = new DataEnc(272);
      e.packData(3002);
      // 走 putBytes（含 4 字节长度前缀），与 Java 端 putBytes 一致
      e.putBytes(new Uint8Array(256).fill(0xFF));
      return e.encode();
    })()
  });

  cases.push({
    name: 'payload all 0x00',
    bytes: (() => {
      const e = new DataEnc(272);
      e.packData(3003);
      e.putBytes(new Uint8Array(256).fill(0x00));
      return e.encode();
    })()
  });

  cases.push({
    name: 'payload 0x00..0xFF',
    bytes: (() => {
      const raw = new Uint8Array(256);
      for (let i = 0; i < 256; i++) raw[i] = i;
      const e = new DataEnc(272);
      e.packData(1101);
      e.putBytes(raw);
      return e.encode();
    })()
  });

  cases.push({
    name: 'negative cmd (-2)',
    bytes: (() => {
      const e = new DataEnc(8);
      e.packData(-2);
      e.putInt(-1);
      return e.encode();
    })()
  });

  cases.push({
    name: 'int boundary values',
    bytes: (() => {
      const e = new DataEnc(64);
      e.packData(2147483647);
      e.setCount(-2147483648);
      e.putInt(-1);
      e.putInt(0);
      e.putInt(1);
      return e.encode();
    })()
  });

  return cases;
}

// ---------------------------------------------------------------- 往返自洽

function roundTripChecks() {
  const failures = [];

  const e = new DataEnc(64);
  e.packData(1002);
  e.setCount(3);
  e.putString('设备A');
  e.putInt(42);
  const udp = e.encodeUdp();

  const dec = DataDec.fromUdp(udp);
  if (dec === null) {
    failures.push('fromUdp 返回 null（魔数校验失败）');
  } else {
    if (dec.getCmd() !== 1002) failures.push(`getCmd=${dec.getCmd()} != 1002`);
    if (dec.getCount() !== 3) failures.push(`getCount=${dec.getCount()} != 3`);
    const s = dec.readString();
    if (s !== '设备A') failures.push(`readString=${s} != 设备A`);
    const n = dec.readInt();
    if (n !== 42) failures.push(`readInt=${n} != 42`);
    if (dec.getLength() !== dec.getByteLen() - DataPacket.HEADER_LEN) {
      failures.push('length 字段与实际 payload 长度不符');
    }
  }

  const junk = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]);
  if (DataDec.fromUdp(junk) !== null) failures.push('魔数不匹配的垃圾包未被丢弃');
  if (DataDec.fromUdp(new Uint8Array(4)) !== null) failures.push('过短的包未被丢弃');

  const e2 = new DataEnc(16);
  e2.packData(1101);
  e2.putString('x');
  const a = hex(e2.encode());
  const b = hex(e2.encode());
  if (a !== b) failures.push('encode() 非幂等（发生二次混淆）');

  const w = new ByteWriter(32);
  w.writeInt(-1);
  w.writeLong(1735689600000);
  w.writeLong(0);
  w.writeString('中文');
  w.writeString('');
  const r = new ByteReader(w.toArray());
  if (r.readInt() !== -1) failures.push('ByteWriter/Reader int 往返失败');
  if (r.readLong() !== 1735689600000) failures.push('ByteWriter/Reader long 往返失败');
  if (r.readLong() !== 0) failures.push('ByteWriter/Reader long(0) 往返失败');
  if (r.readString() !== '中文') failures.push('ByteWriter/Reader string 往返失败');
  if (r.readString() !== '') failures.push('ByteWriter/Reader 空串往返失败');

  // 全字节值映射完备性：混淆/解混淆必须是双射
  let allOk = true;
  for (let v = 0; v < 256; v++) {
    const one = new Uint8Array([v]);
    DataPacket.scramble(one, 1);
    DataPacket.unscramble(one, 0, 1);
    if (one[0] !== v) {
      allOk = false;
      failures.push(`字节 0x${v.toString(16)} 混淆往返不自洽 -> 0x${one[0].toString(16)}`);
      break;
    }
  }
  if (allOk) {
    // 无输出即通过
  }

  return failures;
}

const cases = buildCases();
const out = {
  magic: LanConfig.MAGIC_NUM,
  cases: cases.map((c) => ({ name: c.name, hex: hex(c.bytes) })),
  roundTripFailures: roundTripChecks()
};

process.stdout.write(JSON.stringify(out));
