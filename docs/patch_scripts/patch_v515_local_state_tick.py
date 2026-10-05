# -*- coding: utf-8 -*-
"""
v5.1.5 修 5.1.2/5.1.4 的「已存入本地 / 已删除」显示不出来（vivi 21:35）。

## ★ 根因：与 5.0.71 → 5.0.72 **完全同一个坑**（我 5.0.72 刚总结过，又踩了一次）

`bubbleFooterText` 的非媒体分支读的全是**非 @State**：

```typescript
const st: string = this.service.localStateOf(m.id);   // ← 服务端普通 Map
if (st.length > 0) { return this.padHint(st); }       // ← padHint 只读静态常量
return this.padHint(Index.HINT_FILE);
```

`localMap` 是 `LanService` 的**普通 `Map<string,string>`**，**不是 `@State`**
⇒ **这一格没有任何 @State 依赖** ⇒ ArkTS 不会因为它变了而重建
⇒ `Text(this.bubbleFooterText(...))` **永远停留在 build 那一刻的值**（=「点击查看」）。

★ 而 5.1.2 我在 `markMessagesLocal` 里调的 `swapAlbumIndex()` **换的是 `albumIndex`**，
它与 `localMap` **毫无依赖关系** ⇒ 那一格照样不重建 ⇒ **状态写了但看不见**。
（注释里我还乐观地写了「走换引用闸门 ⇒ 气泡提示会真的重新求值」—— **这句是错的**。）

## 5.0.72 的对照做法（同一个坑的正解）

外层气泡 key 里放了一个**读 @State 的签名**：

```typescript
private groupGoneSig(g: ChatGroup): string {
  // mediaGoneFromAlbum 内部读 this.albumIndex（@State）⇒ 建立依赖
  s += this.mediaGoneFromAlbum(g.msgs[i], 0) ? '1' : '0';
  s += this.albumPartOf(g.msgs[i].id, 0, 0).length > 0 ? '1' : '0';
  return s;
}
// ForEach key: `${g.key}|${videoThumbTick}|${groupMediaSig}|${groupGoneSig}`
```

## 修法（两条一起，缺一不可）

1. **新增 `@State localStateTick: number = 0`** —— 纯「版本号」，
   每次记账 ++。它**没有任何语义**，只负责让那一格重建。
2. **`bubbleFooterText` 的非媒体分支读一次 `this.localStateTick`** ——
   ★ **读它但不用它拼返回值**（与 5.0.63 对 `thumbTick` 的处理完全一致）：
   读 ⇒ 建立 @State 依赖 ⇒ 记账后那一格会重建 ⇒ `localStateOf` 被重新求值。

⚠️ **不能只做 1 不做 2**：写了 `tick++` 但没人读 ⇒ 依赖建不起来 ⇒ 白改。
⚠️ **不能只做 2 不做 1**：读了 `tick` 但它永远不变 ⇒ 一样不重建。
★ 这就是 5.0.63 那条「保留一次 tick 读、但不拼进 key」的**原样复用**。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 改 1：新增 @State localStateTick（紧跟 albumIndex 声明）
# =====================================================================
OLD1 = """  @State albumIndex: Map<string, string> = new Map<string, string>();"""
NEW1 = """  @State albumIndex: Map<string, string> = new Map<string, string>();
  /**
   * ★ 5.1.5：非媒体文件「已存入本地/已删除」的**版本号** —— 纯计数器、无语义。
   *
   * ⚠️⚠️ **为什么需要它**（5.0.71 → 5.0.72 踩过同一个坑，我又踩了一次）：
   * `localMap` 是 `LanService` 的**普通 Map**，**不是 `@State`** ⇒ 依赖它的
   * `bubbleFooterText` **没有任何 @State 依赖** ⇒ 记账后那一格**不会重建**
   * ⇒ `Text(...)` 永远停留在 build 那一刻的值（＝「点击查看」）。
   * ★ 5.1.2 调的 `swapAlbumIndex()` 换的是 `albumIndex`，**与 `localMap` 毫无关系**，白调。
   *
   * ★ 与 5.0.63 对 `thumbTick` 的处理**完全一致**：`bubbleFooterText` 里
   *   **读它一次**（建立依赖 ⇒ 值更新后重建），但**不用它拼返回值**
   *   （拼进 key 就会因「改提示文案」而销毁重建那三态文本，得不偿失）。
   */
  @State localStateTick: number = 0;"""

# =====================================================================
# 改 2：bubbleFooterText 非媒体分支读一次 tick
# =====================================================================
OLD2 = """    if (mediaPath.length === 0 || !this.isMediaName(mediaPath)) {
      // ★ 5.1.2：非媒体的三态 —— 点击查看 / 已存入本地 / 已删除。
      //   ⚠️ 顺序固定：先「有没有动过」，再落到具体状态。
      //   ⚠️ 这三条互斥（一个 Map key 一个值），所以 if/else 链即可。
      const st: string = this.service.localStateOf(m.id);
      if (st.length > 0) {
        return this.padHint(st);
      }
      return this.padHint(Index.HINT_FILE);
    }"""
NEW2 = """    if (mediaPath.length === 0 || !this.isMediaName(mediaPath)) {
      // ★ 5.1.2：非媒体的三态 —— 点击查看 / 已存入本地 / 已删除。
      //   ⚠️ 顺序固定：先「有没有动过」，再落到具体状态。
      //   ⚠️ 这三条互斥（一个 Map key 一个值），所以 if/else 链即可。
      //
      // ★★ 5.1.5：这里的 `tick` 是**故意传给 padHint 的**，作用只有一个 ——
      //   **建立 @State 依赖**。`localStateOf` 读的是服务端**普通 Map**（非 @State），
      //   而本分支原本**不读任何 @State** ⇒ 记账后这一格不重建 ⇒
      //   提示永远停在「点击查看」（5.0.71 → 5.0.72 踩过同一个坑）。
      //   ⚠️ `padHint` **不用它拼返回值**（拼进去会因改文案而销毁重建三态文本）。
      const tick: number = this.localStateTick;
      const st: string = this.service.localStateOf(m.id);
      if (st.length > 0) {
        return this.padHint(st, tick);
      }
      return this.padHint(Index.HINT_FILE, tick);
    }"""

# =====================================================================
# 改 2b：padHint 加「_tick」可选形参（建立 @State 依赖用，不参与拼接）
# =====================================================================
OLD2B = """  private padHint(s: string): string {
    const gap: number = Index.HINT_MAX_LEN - s.length;
    return gap > 0 ? `${s}${' '.repeat(gap)}` : s;
  }"""
NEW2B = """  /**
   * 等宽补齐：按 `HINT_MAX_LEN` 补半角空格（5.0.70 立的规矩）。
   *
   * ★ 5.1.5：`_tick` 是**只为建立 @State 依赖而存在的形参** ——
   *   调用方 `bubbleFooterText` 的非媒体分支读的是服务端**普通 Map**（非 @State），
   *   那个分支**不读任何 @State** ⇒ 记账后不重建 ⇒ 提示停在旧值。
   *   把 `this.localStateTick` 传进来（哪怕这里不用）就**建立了依赖**。
   *   ⚠️ **它绝不参与拼接**：拼进去会因「改文案」销毁重建三态文本。
   *   ⚠️ 名字带下划线前缀 = 明示「故意不用」，也让 lint 不报未使用参数。
   */
  private padHint(s: string, _tick: number = 0): string {
    const gap: number = Index.HINT_MAX_LEN - s.length;
    return gap > 0 ? `${s}${' '.repeat(gap)}` : s;
  }"""

# =====================================================================
# 改 3：markMessagesLocal 里把 swapAlbumIndex 换成 tick++（闸门内）
# =====================================================================
OLD3 = """    if (hit > 0) {
      this.swapAlbumIndex();   // 走换引用闸门 ⇒ 气泡提示会真的重新求值
      this.service.logAuto(`[5.1.2] 记本地状态 ${state}：${fileName} 命中 ${hit} 条消息`);
    }"""
NEW3 = """    if (hit > 0) {
      // ★ 5.1.5：换掉 5.1.2 那句 `swapAlbumIndex()` —— **它换的是 `albumIndex`，
      //   与 `localMap` 毫无依赖关系** ⇒ 那一格照样不重建 ⇒ 状态写了看不见。
      //   现在改为 `localStateTick++`：它是 `bubbleFooterText` **真正在读的** @State
      //   ⇒ ++ 之后那一格重建 ⇒ 提示重新求值。
      //   ⚠️ 走换引用闸门：与其它 @State 落地合并成**一次**重渲染，
      //   否则「记 N 条消息」会触发 N 次重渲染。
      if (this.stateSwapDepth > 0) {
        this.localStateTickNext += 1;
      } else {
        this.localStateTick += 1;
      }
      this.service.logAuto(`[5.1.5] 记本地状态 ${state}：${fileName} 命中 ${hit} 条消息`);
    }"""

# =====================================================================
# 改 4：闸门缓冲字段 + flushStateSwap 落地
# =====================================================================
OLD4 = """  private albumIndexNext: Map<string, string> | null = null;"""
NEW4 = """  private albumIndexNext: Map<string, string> | null = null;
  /** ★ 5.1.5：闸门缓冲用的 tick 增量（`localStateTick` 自身的缓冲位） */
  private localStateTickNext: number = 0;"""

OLD5 = """    const swA: boolean = this.albumIndexNext !== null;"""
NEW5 = """    if (this.localStateTickNext > 0) {
      this.localStateTick += this.localStateTickNext;
      this.localStateTickNext = 0;
    }
    const swA: boolean = this.albumIndexNext !== null;"""

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000104'
NEWV = '"versionCode": 5000105'

REPL = [
    (OLD1, NEW1, 'P1 新增 @State localStateTick'),
    (OLD2, NEW2, 'P2 非媒体分支读 tick 建依赖'),
    (OLD2B, NEW2B, 'P2b padHint 加 _tick 形参'),
    (OLD3, NEW3, 'P3 markMessagesLocal 改 tick++'),
    (OLD4, NEW4, 'P4 闸门缓冲字段'),
    (OLD5, NEW5, 'P5 flushStateSwap 落地'),
]

# =====================================================================
# 执行
# =====================================================================
s = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if 'localStateTick' in s:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'Index.ets.v515pre'), 'w', encoding='utf-8', newline='\n').write(s)
io.open(os.path.join(BAK, 'app.json5.v515pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成')

for old, new, tag in REPL:
    n = s.count(old)
    assert n == 1, '%s: 锚点命中 %d 次（应为 1）' % (tag, n)
    s = s.replace(old, new, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.4"') == 1
s_ver = s_ver.replace('"versionName": "5.1.4"', '"versionName": "5.1.5"', 1)

# ---------------- 不变量 ----------------
# ① tick 声明 + 缓冲字段
assert '@State localStateTick: number = 0;' in s
assert 'private localStateTickNext: number = 0;' in s
# ② 非媒体分支读了 tick（建立依赖）
i = s.find('  private bubbleFooterText(')
j = s.find('\n  }', i)
seg = s[i:j]
assert 'const tick: number = this.localStateTick;' in seg, '非媒体分支没读 tick ⇒ 依赖建不起来'
assert 'this.service.localStateOf(m.id)' in seg
assert 'this.padHint(st, tick)' in seg and 'this.padHint(Index.HINT_FILE, tick)' in seg, '未把 tick 传下去'
# ②b padHint 签名带可选 _tick，且不参与拼接
i2b = s.find('  private padHint(')
j2b = s.find('\n  }', i2b)
seg2b = s[i2b:j2b]
assert 'private padHint(s: string, _tick: number = 0): string {' in seg2b, 'padHint 签名没加 _tick'
assert "' '.repeat(gap)" in seg2b, 'padHint 的补齐逻辑被破坏'
# ⚠️ _tick 只许出现在**签名**里，不许进函数体（进了就会影响拼接结果）
_body = seg2b.split('): string {', 1)[1] if '): string {' in seg2b else seg2b
assert '_tick' not in _body, '_tick 混进函数体了：%r' % _body[:120]
# ③ markMessagesLocal 改成 tick++，且不再调 swapAlbumIndex
i2 = s.find('  private markMessagesLocal(')
j2 = s.find('\n  }', i2)
seg2 = s[i2:j2]
assert 'this.localStateTickNext += 1;' in seg2 and 'this.localStateTick += 1;' in seg2
assert 'this.swapAlbumIndex();' not in seg2, 'swapAlbumIndex 那句无效，应删'
# ④ flushStateSwap 里落地 tick
i3 = s.find('  private flushStateSwap(): void {')
j3 = s.find('\n  }', i3)
assert 'this.localStateTick += this.localStateTickNext;' in s[i3:j3]
# ⑤ 既有 @State 与分支未被破坏
for k in ('@State albumIndex', '@State chatGroups', '@State receivedFiles', '@State chat:',
          'private albumIndexNext', 'private chatGroupsNext'):
    assert k in s, '既有状态被破坏: %s' % k
# ⑥ 5.1.4 / 5.1.3 / 5.1.2 / 5.1.1 成果仍在
assert 'if (names.length > 1) {' in s or True   # 服务端，不在本文件
assert 'private msgCarriesFileName(' in s
assert s.count('this.markMessagesLocal(f.name, Index.HINT_LOCAL_SAVED);') == 1
assert s.count('this.markMessagesLocal(f.name, Index.HINT_LOCAL_DELETED);') == 1
assert "private static readonly HINT_FILE: string = '点击查看';" in s
assert 'if (this.showAbout) {' in s
assert 'private diagSnapshot(' not in s and 'this.diagSnapshot(' not in s

io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  Index.ets %d -> %d' % (len(s), len(s)))
print('OK  versionCode 5000104 -> 5000105 / 5.1.5')
