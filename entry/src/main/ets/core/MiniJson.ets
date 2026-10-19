/**
 * 极简 JSON 解析 / 生成器。
 *
 * ## 为什么不用内置 JSON.parse
 * 1. ArkTS 里 `JSON.parse` 的返回类型是 Object，取字段要层层 `as` 断言，
 *    遇到字段缺失/类型不符时是运行期崩溃而不是可判定的默认值。
 * 2. 本项目解析的是**对端 Android 端 fastjson 生成的**报文，
 *    字段缺失、额外字段、数字被写成浮点都是常态，
 *    需要一个「宽容取值」的层（getString(默认值) 这类）。
 * 3. 自己实现的解析器可以进单测（见 tests/protocol-bytecheck），
 *    用真实的 fastjson 样例字节验证，比"相信库"可靠。
 *
 * ## 支持范围
 * 完整 JSON 语法子集：对象、数组、字符串（含 \" \\ \/ \b \f \n \r \t \uXXXX）、
 * 数字（整数/小数/指数）、true / false / null。
 * 不支持流式解析 —— 报文都是整包字符串，够用。
 */
export class JsonNode {
  static readonly T_NULL: number = 0;
  static readonly T_BOOL: number = 1;
  static readonly T_NUM: number = 2;
  static readonly T_STR: number = 3;
  static readonly T_ARR: number = 4;
  static readonly T_OBJ: number = 5;

  kind: number = JsonNode.T_NULL;
  private sVal: string = '';
  private nVal: number = 0;
  private bVal: boolean = false;
  private aVal: JsonNode[] = [];
  private oVal: Map<string, JsonNode> = new Map<string, JsonNode>();

  static ofNull(): JsonNode {
    return new JsonNode();
  }

  static ofBool(v: boolean): JsonNode {
    const n: JsonNode = new JsonNode();
    n.kind = JsonNode.T_BOOL;
    n.bVal = v;
    return n;
  }

  static ofNum(v: number): JsonNode {
    const n: JsonNode = new JsonNode();
    n.kind = JsonNode.T_NUM;
    n.nVal = v;
    return n;
  }

  static ofStr(v: string): JsonNode {
    const n: JsonNode = new JsonNode();
    n.kind = JsonNode.T_STR;
    n.sVal = v;
    return n;
  }

  static ofArray(items: JsonNode[]): JsonNode {
    const n: JsonNode = new JsonNode();
    n.kind = JsonNode.T_ARR;
    n.aVal = items;
    return n;
  }

  static ofObject(fields: Map<string, JsonNode>): JsonNode {
    const n: JsonNode = new JsonNode();
    n.kind = JsonNode.T_OBJ;
    n.oVal = fields;
    return n;
  }

  // ---------------- 取值（带默认值，永不抛异常） ----------------

  get isNull(): boolean {
    return this.kind === JsonNode.T_NULL;
  }

  isObject(): boolean {
    return this.kind === JsonNode.T_OBJ;
  }

  isArray(): boolean {
    return this.kind === JsonNode.T_ARR;
  }

  /** 对象取字段；不是对象或字段不存在返回 null */
  field(key: string): JsonNode | null {
    if (this.kind !== JsonNode.T_OBJ) {
      return null;
    }
    const v: JsonNode | undefined = this.oVal.get(key);
    return v === undefined ? null : v;
  }

  /** 数组取元素；下标越界返回 null */
  at(index: number): JsonNode | null {
    if (this.kind !== JsonNode.T_ARR || index < 0 || index >= this.aVal.length) {
      return null;
    }
    return this.aVal[index];
  }

  /** 数组长度；不是数组返回 0 */
  get count(): number {
    return this.kind === JsonNode.T_ARR ? this.aVal.length : 0;
  }

  /**
   * 对象的所有字段名（顺序为报文里的原始顺序）。
   * 不是对象返回空数组。用于遍历 / 自测工具。
   */
  keys(): string[] {
    const out: string[] = [];
    if (this.kind !== JsonNode.T_OBJ) {
      return out;
    }
    this.oVal.forEach((_v: JsonNode, k: string) => {
      out.push(k);
    });
    return out;
  }

  /**
   * 取字符串。数字/布尔会被宽容地转成字符串 ——
   * fastjson 有时把纯数字的设备名写成 number，不能让这种小事把传输打断。
   */
  asString(def: string = ''): string {
    switch (this.kind) {
      case JsonNode.T_STR: return this.sVal;
      case JsonNode.T_NUM: return `${this.nVal}`;
      case JsonNode.T_BOOL: return this.bVal ? 'true' : 'false';
      default: return def;
    }
  }

  /** 取数字。字符串里是合法数字时也接受 */
  asNumber(def: number = 0): number {
    if (this.kind === JsonNode.T_NUM) {
      return this.nVal;
    }
    if (this.kind === JsonNode.T_STR) {
      const v: number = Number.parseFloat(this.sVal);
      return Number.isNaN(v) ? def : v;
    }
    if (this.kind === JsonNode.T_BOOL) {
      return this.bVal ? 1 : 0;
    }
    return def;
  }

  asBool(def: boolean = false): boolean {
    switch (this.kind) {
      case JsonNode.T_BOOL: return this.bVal;
      case JsonNode.T_NUM: return this.nVal !== 0;
      case JsonNode.T_STR: return this.sVal === 'true';
      default: return def;
    }
  }
}

/** 解析失败的统一返回值 */
export class JsonParseResult {
  ok: boolean = false;
  root: JsonNode = JsonNode.ofNull();
  error: string = '';
}

export class MiniJson {
  /** 最大嵌套深度，防恶意深嵌套导致栈溢出 */
  private static readonly MAX_DEPTH: number = 64;

  private src: string = '';
  private pos: number = 0;
  private err: string = '';

  /** 解析 JSON 文本。失败时返回 T_NULL 节点并给出 error */
  static parse(text: string): JsonParseResult {
    const out: JsonParseResult = new JsonParseResult();
    const p: MiniJson = new MiniJson();
    p.src = text;
    p.pos = 0;
    try {
      p.skipWs();
      const node: JsonNode = p.parseValue(0);
      p.skipWs();
      // 必须整串消费完。报文的 JSON 是**长度前缀字符串**（ProtoIO.readString），
      // 若尾部还有残留内容，说明帧解析脱节 —— 此时宁可明确失败，
      // 也不要拿着一半正确的 Object 继续跑（会把设备/文件清单悄悄弄错）。
      if (p.pos !== p.src.length) {
        p.fail(`JSON 尾部有 ${p.src.length - p.pos} 字节多余内容`);
      }
      out.root = node;
      out.ok = true;
    } catch (e) {
      const err: Error = e as Error;
      out.ok = false;
      out.error = `${err.message}（偏移 ${p.pos}）`;
    }
    return out;
  }

  /** 生成 JSON 字符串字面量（含首尾引号），做完整转义 */
  static quote(s: string): string {
    let out: string = '"';
    for (let i = 0; i < s.length; i++) {
      const c: string = s.charAt(i);
      const code: number = s.charCodeAt(i);
      switch (c) {
        case '"': out += '\\"'; break;
        case '\\': out += '\\\\'; break;
        case '\n': out += '\\n'; break;
        case '\r': out += '\\r'; break;
        case '\t': out += '\\t'; break;
        case '\b': out += '\\b'; break;
        case '\f': out += '\\f'; break;
        default:
          if (code < 0x20) {
            // 控制字符必须转义，否则非法 JSON
            out += `\\u${code.toString(16).padStart(4, '0')}`;
          } else {
            out += c;
          }
      }
    }
    return `${out}"`;
  }

  // ------------------------------------------------------------------
  // 递归下降
  // ------------------------------------------------------------------

  private fail(msg: string): never {
    throw new Error(msg);
  }

  private skipWs(): void {
    while (this.pos < this.src.length) {
      const c: string = this.src.charAt(this.pos);
      if (c === ' ' || c === '\t' || c === '\n' || c === '\r') {
        this.pos += 1;
      } else {
        break;
      }
    }
  }

  private peek(): string {
    return this.pos < this.src.length ? this.src.charAt(this.pos) : '';
  }

  private expect(ch: string): void {
    if (this.peek() !== ch) {
      this.fail(`期望 '${ch}'`);
    }
    this.pos += 1;
  }

  private parseValue(depth: number): JsonNode {
    if (depth > MiniJson.MAX_DEPTH) {
      this.fail('JSON 嵌套过深');
    }
    const c: string = this.peek();
    if (c === '') {
      this.fail('意外的末尾');
    }
    if (c === '{') {
      return this.parseObject(depth);
    }
    if (c === '[') {
      return this.parseArray(depth);
    }
    if (c === '"') {
      return JsonNode.ofStr(this.parseString());
    }
    if (c === 't') {
      this.expectWord('true');
      return JsonNode.ofBool(true);
    }
    if (c === 'f') {
      this.expectWord('false');
      return JsonNode.ofBool(false);
    }
    if (c === 'n') {
      this.expectWord('null');
      return JsonNode.ofNull();
    }
    return JsonNode.ofNum(this.parseNumber());
  }

  private expectWord(w: string): void {
    if (this.src.substr(this.pos, w.length) !== w) {
      this.fail(`期望 ${w}`);
    }
    this.pos += w.length;
  }

  private parseObject(depth: number): JsonNode {
    this.expect('{');
    const fields: Map<string, JsonNode> = new Map<string, JsonNode>();
    this.skipWs();
    if (this.peek() === '}') {
      this.pos += 1;
      return JsonNode.ofObject(fields);
    }
    while (true) {
      this.skipWs();
      const key: string = this.parseString();
      this.skipWs();
      this.expect(':');
      this.skipWs();
      fields.set(key, this.parseValue(depth + 1));
      this.skipWs();
      const c: string = this.peek();
      if (c === ',') {
        this.pos += 1;
        continue;
      }
      if (c === '}') {
        this.pos += 1;
        return JsonNode.ofObject(fields);
      }
      this.fail(`对象里期望 ',' 或 '}'，实际 '${c}'`);
    }
  }

  private parseArray(depth: number): JsonNode {
    this.expect('[');
    const items: JsonNode[] = [];
    this.skipWs();
    if (this.peek() === ']') {
      this.pos += 1;
      return JsonNode.ofArray(items);
    }
    while (true) {
      this.skipWs();
      items.push(this.parseValue(depth + 1));
      this.skipWs();
      const c: string = this.peek();
      if (c === ',') {
        this.pos += 1;
        continue;
      }
      if (c === ']') {
        this.pos += 1;
        return JsonNode.ofArray(items);
      }
      this.fail(`数组里期望 ',' 或 ']'，实际 '${c}'`);
    }
  }

  private parseString(): string {
    this.expect('"');
    let out: string = '';
    while (true) {
      if (this.pos >= this.src.length) {
        this.fail('字符串未闭合');
      }
      const c: string = this.src.charAt(this.pos);
      this.pos += 1;
      if (c === '"') {
        return out;
      }
      if (c !== '\\') {
        out += c;
        continue;
      }
      // 转义序列
      if (this.pos >= this.src.length) {
        this.fail('转义未完成');
      }
      const e: string = this.src.charAt(this.pos);
      this.pos += 1;
      switch (e) {
        case '"': out += '"'; break;
        case '\\': out += '\\'; break;
        case '/': out += '/'; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case 'n': out += '\n'; break;
        case 'r': out += '\r'; break;
        case 't': out += '\t'; break;
        case 'u': {
          if (this.pos + 4 > this.src.length) {
            this.fail('\\u 转义不完整');
          }
          const hex: string = this.src.substr(this.pos, 4);
          const code: number = Number.parseInt(hex, 16);
          if (Number.isNaN(code)) {
            this.fail(`非法 \\u 转义: ${hex}`);
          }
          this.pos += 4;
          out += String.fromCharCode(code);
          break;
        }
        default:
          this.fail(`未知转义 \\${e}`);
      }
    }
  }

  private parseNumber(): number {
    const start: number = this.pos;
    if (this.peek() === '-') {
      this.pos += 1;
    }
    while (this.isDigit(this.peek())) {
      this.pos += 1;
    }
    if (this.peek() === '.') {
      this.pos += 1;
      while (this.isDigit(this.peek())) {
        this.pos += 1;
      }
    }
    const ec: string = this.peek();
    if (ec === 'e' || ec === 'E') {
      this.pos += 1;
      const sign: string = this.peek();
      if (sign === '+' || sign === '-') {
        this.pos += 1;
      }
      while (this.isDigit(this.peek())) {
        this.pos += 1;
      }
    }
    if (this.pos === start) {
      this.fail(`非法数字起始字符 '${this.peek()}'`);
    }
    const text: string = this.src.substring(start, this.pos);
    const v: number = Number.parseFloat(text);
    if (Number.isNaN(v)) {
      this.fail(`非法数字: ${text}`);
    }
    return v;
  }

  private isDigit(c: string): boolean {
    return c >= '0' && c <= '9';
  }
}
