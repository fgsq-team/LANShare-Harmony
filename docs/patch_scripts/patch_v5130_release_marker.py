# -*- coding: utf-8 -*-
"""
v5.1.13 —— 版本标识：**5.1.12 是最后一个正式版，之后都是测试版**

vivi 2026-10-03 09:52 定：「把 5.1.12 版本标记为正式版，其他都是测试版」。

## 做法：按**版本号**判定，而不是按「当前构建是不是最新」
判据 = 与 `LAST_STABLE_VER`（'5.1.12'）做**逐段数字比较**：
  - 5.1.12 及更早（含 5.1.9 / 5.1.0）⇒ **正式版**
  - 5.1.13 及以后（5.1.14 / 5.2.0 / 6.0.0）⇒ **测试版**

⚠️ 为什么不用「构建时间/版本号 > 上次发布」这种说法：
  正式版与测试版是**发布通道的属性**，不是「新旧」的属性。
  往后若把 5.1.14 定为正式版，**只要改 `LAST_STABLE_VER` 一个常量**，
  5.1.14 立刻自动变成正式版 —— 不用改任何界面代码。

## 改动
  1. 新增 `LAST_STABLE_VER` + `isTestVersion(ver)` + `versionBadgeOf(ver)` 三个顶层常量/函数。
  2. 关于页版本号那行加一个**「测试版」角标**（仅测试版显示，正式版不显示，保持干净）。
  3. `ABOUT_FALLBACK_VER` 从 '5.1.0' 同步到 '5.1.13'（5.0.29 起就是发版必做项）。

不碰：不改 versionName 的取值方式（仍以 bundleManager 运行时值为准），
     不加任何网络请求，不影响传输/协议。
"""
import io, os, sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
IDX = os.path.join(ROOT, 'entry/src/main/ets/pages/Index.ets')

# ---------------------------------------------------------------- 1. 三个新符号
OLD1 = """/** 版本号兜底：运行时 bundleManager 取不到（或取到空串）时用这个，与 app.json5 同步 */
const ABOUT_FALLBACK_VER: string = '5.1.0';"""

NEW1 = """/** 版本号兜底：运行时 bundleManager 取不到（或取到空串）时用这个，与 app.json5 同步 */
const ABOUT_FALLBACK_VER: string = '5.1.13';

/**
 * ★ 5.1.13（vivi 09:52「把 5.1.12 标记为正式版，其他都是测试版」）：
 * **最后一个正式版**的版本号。
 *
 * ## 判据是「发布通道」，不是「新旧」
 * `5.1.12` 及更早 = 正式版；`5.1.13` 及以后 = 测试版。
 * 往后把某版定为正式版时，**只改这一个常量**即可，
 * 那一版立刻自动去掉「测试版」角标，界面代码一行都不用动。
 *
 * ⚠️ 比较方式必须是**逐段数字**比较，不能比字符串：
 *   `'5.1.9' > '5.1.12'` 在字符串比较下是**假的**（'9' > '1'），
 *   会把 5.1.9 误判成测试版。必须拆成数字数组逐段比。
 */
const LAST_STABLE_VER: string = '5.1.12';

/** 版本号 → 数字段数组。'5.1.13' → [5,1,13]；非数字段按 0 处理（宁当旧版，不误标测试） */
function verParts(ver: string): number[] {
  const out: number[] = [];
  const parts: string[] = ver.split('.');
  for (let i: number = 0; i < parts.length; i++) {
    const n: number = Number(parts[i]);
    out.push(isNaN(n) ? 0 : n);
  }
  return out;
}

/**
 * 逐段数字比较：a > b 返回 true，a <= b 返回 false。
 * 段数不同时按 0 补齐（'5.1' 与 '5.1.0' 视为相同）。
 */
function verGreater(a: string, b: string): boolean {
  const pa: number[] = verParts(a);
  const pb: number[] = verParts(b);
  const n: number = Math.max(pa.length, pb.length);
  for (let i: number = 0; i < n; i++) {
    const va: number = i < pa.length ? pa[i] : 0;
    const vb: number = i < pb.length ? pb[i] : 0;
    if (va > vb) {
      return true;
    }
    if (va < vb) {
      return false;
    }
  }
  return false;
}

/** 是否测试版：版本号 > LAST_STABLE_VER */
function isTestVersion(ver: string): boolean {
  if (ver.length === 0) {
    return false;
  }
  return verGreater(ver, LAST_STABLE_VER);
}"""

# ---------------------------------------------------------------- 2. 关于页角标
OLD2 = """          // ---------------- 版本号 ----------------
          Row({ space: 8 }) {
            Text('版本')
              .fontSize(13)
              .fontColor(C_SUB)
            Text(this.aboutVer)
              .fontSize(13)
              .fontWeight(FontWeight.Medium)
              .fontColor(C_TEXT)
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)"""

NEW2 = """          // ---------------- 版本号（+ 测试版角标）----------------
          Row({ space: 8 }) {
            Text('版本')
              .fontSize(13)
              .fontColor(C_SUB)
            Text(this.aboutVer)
              .fontSize(13)
              .fontWeight(FontWeight.Medium)
              .fontColor(C_TEXT)
            // ★ 5.1.13：只在测试版显示角标，正式版**什么都不加**（保持干净）。
            //   判据用 `isTestVersion(this.aboutVer)` 而不是 `!== LAST_STABLE_VER`
            //   —— 后者会把 5.1.9 这种**更早的正式版**也标成测试版。
            if (isTestVersion(this.aboutVer)) {
              Text('测试版')
                .fontSize(11)
                .fontWeight(FontWeight.Medium)
                .fontColor('#FFFFFF')
                .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                .backgroundColor('#E8833A')
                .borderRadius(4)
            }
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)"""

EDITS = [(OLD1, NEW1), (OLD2, NEW2)]

s = io.open(IDX, encoding='utf-8').read()

if '--dry' in sys.argv:
    for old, new in EDITS:
        c = s.count(old)
        print('  OLD 命中 %d' % c)
        assert c == 1, c
        s = s.replace(old, new, 1)
    print('DRY-RUN OK')
    raise SystemExit(0)

for old, new in EDITS:
    c = s.count(old)
    assert c == 1, 'OLD 命中 %d（应 1）' % c
    s = s.replace(old, new, 1)

assert '\r\n' not in s, 'CRLF 混入'
# ⚠️ 只校验**本次新增的文本**：磁盘原文 Index.ets:3585 有一行历史注释
#    含 3 个坏字符（`那���格` 本该是「那一格」，早期编码事故），
#    它不影响编译，也不属本次改动范围 —— 全文件断言会误拦。
for old, new in EDITS:
    assert '\ufffd' not in new, '新增文本含坏字符'
io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
print('APPLIED  %d chars' % len(s))
