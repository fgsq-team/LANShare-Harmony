/**
 * 网页客户端的访问白名单。
 *
 * ## 为什么需要它
 * 原 Android 版（`web/LHttpServer.java` + `db/TokenDBUtil.java`）对网页访问实行
 * **「新客户端需手机端确认」** 的授权模型，这不是缺陷而是它的设计：
 *
 * ```
 * 浏览器首次访问
 *   → POST /initConfig（带 IP）
 *      → 服务端按 IP 查 token 表，查不到 ⇒ 建一条 pass=0 的记录
 *      → 发 SERVICE_HTTP_NEW_CLIENT 消息 ⇒ 手机端弹「是否允许该设备访问网页」
 *      → 返回 {rootPath, name, token, pass:false}
 *   → 网页弹「没有访问权限，请在手机上同意之后刷新页面」
 *   → 每 2 秒轮询 POST /checkPass
 *      → 手机点「同意」把 pass 置 1 ⇒ /checkPass 返回 {pass:true} ⇒ 网页 location.reload()
 * ```
 *
 * 另有一个全局开关 `Config.WEB_OPEN`：开启后新客户端直接 pass=1，不再需要确认。
 *
 * 鸿蒙侧早期实现只返回了 `{deviceName, udpPort, ...}`，网页拿到的 `a.pass` 是
 * `undefined`（falsy）⇒ 弹提示 ⇒ 再轮询 `/checkPass` 拿到的还是 `undefined`
 * ⇒ **永远进不去**。这就是真机「浏览器访问网址提示没有访问权限」的根因。
 *
 * ## 与 Android 的差异
 * Android 用 SQLite（`token_list_new_v1.db`）存；鸿蒙侧没有等价的三方数据库需求，
 * 直接用 preferences 存一份 JSON 数组，语义字段一一对应：
 * `id→token`、`ip→ip`、`name→name`、`pass→pass`、`custom→custom`、`isdel→（删除即移除）`。
 */

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

export const common = {};

export class BusinessError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

import { Log } from '../core/Logger.ts';
import { JsonNode, JsonParseResult, MiniJson } from '../core/MiniJson.ts';

const TAG: string = 'WebClientStore';

/** 与 HttpRouter 共用同一个 preferences 文件 */
const PREF_NAME: string = 'lanshare_web';
const KEY_CLIENTS: string = 'webClients';
/** 最多保留的客户端条数，超出按 lastSeen 淘汰最旧的 */
const MAX_CLIENTS: number = 64;
/** pass=1 且长期不再出现的记录，超过这个时长可选择清理（当前不主动清理） */
const MAX_NAME_LEN: number = 64;

/** 一个网页客户端。字段名对齐 Android 的 Token 实体 */
export class WebClient {
  token: string = '';
  ip: string = '';
  name: string = '';
  /** 是否已放行。对应 TokenDBUtil 的 pass 列（1 = 已同意） */
  pass: boolean = false;
  /** 是否由用户手工命名过。对应 custom 列 */
  custom: boolean = false;
  createdMs: number = 0;
  lastSeenMs: number = 0;

  clone(): WebClient {
    const c: WebClient = new WebClient();
    c.token = this.token;
    c.ip = this.ip;
    c.name = this.name;
    c.pass = this.pass;
    c.custom = this.custom;
    c.createdMs = this.createdMs;
    c.lastSeenMs = this.lastSeenMs;
    return c;
  }
}

export class WebClientStore {
  private ctx: common.UIAbilityContext | null = null;
  private list: WebClient[] = [];
  private ready: boolean = false;

  /** 读取持久化数据。失败不抛，退化为「空表」（等于每个客户端都要重新确认一次） */
  async init(ctx: common.UIAbilityContext): Promise<void> {
    this.ctx = ctx;
    try {
      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_NAME);
      const raw: string = await store.get(KEY_CLIENTS, '') as string;
      this.list = WebClientStore.deserialize(raw);
      this.ready = true;
      Log.i(TAG, `网页客户端白名单已载入：${this.list.length} 条`);
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `载入网页客户端白名单失败: ${err.code} ${err.message}`);
      this.list = [];
      this.ready = true;
    }
  }

  get isReady(): boolean {
    return this.ready;
  }

  get count(): number {
    return this.list.length;
  }

  /** 按客户端 IP 查（原实现 queryCustonIp）。一个 IP 只保留一条 */
  byIp(ip: string): WebClient | null {
    for (let i = 0; i < this.list.length; i++) {
      if (this.list[i].ip === ip) {
        return this.list[i];
      }
    }
    return null;
  }

  /** 按 token 查（原实现 queryByToken） */
  byToken(token: string): WebClient | null {
    if (token.length === 0) {
      return null;
    }
    for (let i = 0; i < this.list.length; i++) {
      if (this.list[i].token === token) {
        return this.list[i];
      }
    }
    return null;
  }

  /**
   * 登记一个新客户端，pass 默认 false（等手机端确认）。
   * 调用方随后应把它呈现到 UI。
   */
  add(ip: string, name: string, pass: boolean): WebClient {
    const c: WebClient = new WebClient();
    c.token = WebClientStore.newToken();
    c.ip = ip;
    c.name = name;
    c.pass = pass;
    c.custom = false;
    c.createdMs = Date.now();
    c.lastSeenMs = c.createdMs;
    this.list.push(c);
    this.evictIfNeeded();
    return c;
  }

  /** 用户点了「同意 / 拒绝」。返回是否命中了记录 */
  setPass(token: string, pass: boolean): boolean {
    const c: WebClient | null = this.byToken(token);
    if (c === null) {
      return false;
    }
    c.pass = pass;
    c.lastSeenMs = Date.now();
    return true;
  }

  /** 网页端改名（/updateWebName） */
  updateName(token: string, name: string): boolean {
    const c: WebClient | null = this.byToken(token);
    if (c === null) {
      return false;
    }
    c.name = name.length > MAX_NAME_LEN ? name.substring(0, MAX_NAME_LEN) : name;
    c.custom = true;
    return true;
  }

  /** 删除某条记录（UI 里「拒绝」并移除时可调用） */
  remove(token: string): boolean {
    for (let i = 0; i < this.list.length; i++) {
      if (this.list[i].token === token) {
        this.list.splice(i, 1);
        return true;
      }
    }
    return false;
  }

  /** 等待用户确认的客户端（pass=false），UI 用它渲染授权卡片 */
  pending(): WebClient[] {
    const out: WebClient[] = [];
    for (let i = 0; i < this.list.length; i++) {
      if (!this.list[i].pass) {
        out.push(this.list[i]);
      }
    }
    return out;
  }

  /** 全部客户端（UI 里可展示已放行列表） */
  all(): WebClient[] {
    const out: WebClient[] = [];
    for (let i = 0; i < this.list.length; i++) {
      out.push(this.list[i]);
    }
    return out;
  }

  /** 触达即刷新时间戳，用于淘汰与 UI 排序 */
  touch(c: WebClient): void {
    c.lastSeenMs = Date.now();
  }

  /** 落盘。失败只记日志——授权状态丢失只是要重新确认一次，不该把请求打挂 */
  async flush(): Promise<void> {
    if (this.ctx === null) {
      return;
    }
    try {
      const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_NAME);
      await store.put(KEY_CLIENTS, WebClientStore.serialize(this.list));
      await store.flush();
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `保存网页客户端白名单失败: ${err.code} ${err.message}`);
    }
  }

  /** 把 query 里带的 token 归一化（去掉首尾空白与引号） */
  static normalizeToken(raw: string): string {
    let t: string = raw.trim();
    if (t.length >= 2 && ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'")))) {
      t = t.substring(1, t.length - 1);
    }
    return t;
  }

  /**
   * 生成 32 位十六进制 token。
   * 用 `Math.imul(...) >>> 0` 而不是 `*`：后者结果可超 2^53 失去精度，
   * 且 `^` 会把值折成有符号 int32（这个坑在设备 uuid 上已经踩过一次）。
   */
  private static newToken(): string {
    const seed: string = `${Date.now()}-${Math.floor(Math.random() * 1e12)}-${Math.random()}`;
    let h1: number = 2166136261;
    let h2: number = 5381;
    for (let i = 0; i < seed.length; i++) {
      const c: number = seed.charCodeAt(i);
      h1 = Math.imul(h1 ^ c, 16777619) >>> 0;
      h2 = Math.imul(h2, 33) + c >>> 0;
    }
    const g1: number = Math.imul(h1 ^ h2, 2654435761) >>> 0;
    const g2: number = Math.imul(h1 + h2, 2246822519) >>> 0;
    return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0')
      + g1.toString(16).padStart(8, '0') + g2.toString(16).padStart(8, '0');
  }

  /** 超出上限时淘汰最久未使用的已放行记录（等待确认的记录不淘汰） */
  private evictIfNeeded(): void {
    if (this.list.length <= MAX_CLIENTS) {
      return;
    }
    this.list.sort((a: WebClient, b: WebClient) => a.lastSeenMs - b.lastSeenMs);
    while (this.list.length > MAX_CLIENTS) {
      const victim: WebClient = this.list[0];
      if (!victim.pass) {
        // 有未确认的记录，往后找一条已放行的
        let idx: number = -1;
        for (let i = 1; i < this.list.length; i++) {
          if (this.list[i].pass) {
            idx = i;
            break;
          }
        }
        if (idx < 0) {
          return; // 全是待确认，先不淘汰
        }
        this.list.splice(idx, 1);
      } else {
        this.list.splice(0, 1);
      }
    }
  }

  // ------------------------------------------------------------------
  // 序列化：手写，避免依赖 JSON.stringify 的类型陷阱
  // ------------------------------------------------------------------

  private static serialize(list: WebClient[]): string {
    const parts: string[] = [];
    for (let i = 0; i < list.length; i++) {
      const c: WebClient = list[i];
      parts.push(
        `{"token":${WebClientStore.quote(c.token)},"ip":${WebClientStore.quote(c.ip)},` +
        `"name":${WebClientStore.quote(c.name)},"pass":${c.pass ? 'true' : 'false'},` +
        `"custom":${c.custom ? 'true' : 'false'},"createdMs":${c.createdMs},"lastSeenMs":${c.lastSeenMs}}`
      );
    }
    return `[${parts.join(',')}]`;
  }

  /** 解析失败一律退化为空表，绝不让坏数据把网页端卡死 */
  private static deserialize(raw: string): WebClient[] {
    const out: WebClient[] = [];
    if (raw.length === 0) {
      return out;
    }
    const parsed: JsonParseResult = MiniJson.parse(raw);
    if (!parsed.ok || !parsed.root.isArray()) {
      Log.w(TAG, '网页客户端白名单内容无法解析，按空表处理');
      return out;
    }
    const root: JsonNode = parsed.root;
    for (let i = 0; i < root.count; i++) {
      const n: JsonNode | null = root.at(i);
      if (n === null || !n.isObject()) {
        continue;
      }
      const c: WebClient = new WebClient();
      c.token = WebClientStore.strField(n, 'token');
      c.ip = WebClientStore.strField(n, 'ip');
      c.name = WebClientStore.strField(n, 'name');
      c.pass = WebClientStore.boolField(n, 'pass');
      c.custom = WebClientStore.boolField(n, 'custom');
      c.createdMs = WebClientStore.numField(n, 'createdMs');
      c.lastSeenMs = WebClientStore.numField(n, 'lastSeenMs');
      if (c.token.length > 0) {
        out.push(c);
      }
    }
    return out;
  }

  /** JsonNode.field() 返回可空，这里统一收口，避免每处都判空 */
  private static strField(n: JsonNode, key: string): string {
    const v: JsonNode | null = n.field(key);
    return v === null ? '' : v.asString('');
  }

  private static numField(n: JsonNode, key: string): number {
    const v: JsonNode | null = n.field(key);
    return v === null ? 0 : v.asNumber(0);
  }

  private static boolField(n: JsonNode, key: string): boolean {
    const v: JsonNode | null = n.field(key);
    return v === null ? false : v.asBool(false);
  }

  private static quote(s: string): string {
    let out: string = '"';
    for (let i = 0; i < s.length; i++) {
      const c: string = s.charAt(i);
      if (c === '"') {
        out += '\\"';
      } else if (c === '\\') {
        out += '\\\\';
      } else if (c === '\n') {
        out += '\\n';
      } else if (c === '\r') {
        out += '\\r';
      } else if (c === '\t') {
        out += '\\t';
      } else {
        out += c.charCodeAt(0) < 0x20 ? ' ' : c;
      }
    }
    return `${out}"`;
  }
}
