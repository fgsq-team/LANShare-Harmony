# -*- coding: utf-8 -*-
"""5.1.10 的判据写进 MEMORY + 今日日志 + 版本编年。"""
import io

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
VER = r'E:\lanshare项目\.workbuddy\memory\VERSION_HISTORY.md'

s = io.open(MEM, encoding='utf-8').read()
if '5.1.10' not in s:
    ANCHOR = '7. ★ **`hdc` 无设备时交付不停**（夸克网盘）'
    assert s.count(ANCHOR) == 1, s.count(ANCHOR)
    ADD = '''4p. ★★★★★★★★★ **「标记文件存在」当判据前，先问「它会不会被自己重写」**（5.1.10，5.0.49 起的老 bug）。
    闪退检测用 `run.lock`：`initLogFile` 开头 `accessSync(lock)` 判「上次是否闪退」，
    **同一次启动的末尾又 `openSync(lock, CREATE|TRUNC)` 把它写回来**
    ⇒ 下次启动 `accessSync` **必然 true** ⇒ **每次启动都判成闪退**、每次都弹提示。
    ★ 通则：**一个「存在即真」的标记，若本次运行会写它，它就永远为真**。
    ✅ 正确做法 = 引入**不会被自己重写的独立标记**（本项目 `crash.flag`），三步闭环：
      ① 启动时**读**（判上次）+ ② 启动末尾**写**（本次已起来）+ ③ 正常退出**删**（本次正常）
    ⇒ 正常退出→被删→不提示；中途崩→留下→**只提示一次**。
    ★ 判据：**这个文件的语义是「存在」还是「上次没被清理」**？
       后者必须有一个**独立载体**，不能靠「自己会重写的文件」。
    ★ 配套：提示类 UI（toast）要加**一次性守卫**（本项目 `crashTipShown`）——
       切前台恢复共享会**再跑一次**同一条路径。
    ★★ **别为了让提示消失而删掉提示本身** —— 它是**真机唯一的排障通路**（5.0.49 的原意）。
       要修的是「它该只在真闪退后出现一次」，不是「它不该出现」。
4q. ★★ **改 python 补丁脚本时，别在 heredoc 里做「改名 / 改长块」**（5.1.10 又踩）。
    我用 `python - <<'EOF'` 改脚本里的变量名，转义把我的意图搅了
    （`OLDS2` 变成「`flagExists` 声明 + `lockExists` 赋值」的**混合体**，锚点命中 0）。
    ★ **规则**：改名/改多行块 ⇒ **用 Edit 工具**；heredoc 只适合「跑一段无状态检查」。
    ★ 这已是同一条老规矩的第 N 次（5.0.63 起）：**heredoc 适合执行，不适合编辑**。
'''
    s = s.replace(ANCHOR, ADD + ANCHOR, 1)
    assert '5.1.10' in s and chr(0xFFFD) not in s
    io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
    print('OK MEMORY -> %d' % len(s))
else:
    print('MEMORY 已有 5.1.10，跳过')

s2 = io.open(VER, encoding='utf-8').read()
if '5.1.10' not in s2:
    s2 = s2.rstrip('\n') + '''

## 5.1.10（2026-10-02 22:00）
- 修「**每次启动都提示『检测到上次闪退』**」（**5.0.49 起的老 bug**）。
  根因：`initLogFile` 开头 `accessSync(run.lock)` 判「上次是否闪退」，
  **同一次启动末尾又把它 TRUNC 重写** ⇒ 它的「存在」永远为真 ⇒ 每次都判成闪退。
- 修法：判据改用**独立标记 `crash.flag`**（不会被自己重写），三步闭环：
  启动时读 / 启动末尾写 / `markCleanExit` 删。
  另加 `Index.crashTipShown` 一次性守卫（切前台会重跑 `autoStart`）。
- ⚠️ **刻意没删提示本身** —— 它是**真机唯一的排障通路**（5.0.49 的原意）。
'''
    io.open(VER, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK VERSION_HISTORY -> %d' % len(s2))

s3 = io.open(LOG, encoding='utf-8').read()
if 'v5.1.10' not in s3:
    s3 = s3.rstrip('\n') + '''

## 22:00 v5.1.10 —— 修「每次启动都提示上次闪退」（5.0.49 起的老 bug）

### ★★ 根因：一个「存在即真」的标记，被自己重写了
`initLogFile` 的流程：
1. `accessSync(run.lock)` 存在 ⇒ `prevCrashed = true`
2. ……
3. **最后又 `openSync(run.lock, CREATE|TRUNC)` 重写它**（写本次启动时间）

⇒ 第 3 步在**同一次启动末尾就写回来了** ⇒ 下次启动第 1 步**必然为 true**
⇒ **每次启动都判成闪退、每次都弹提示**。

`markCleanExit`（正常退出时 `onDestroy` 调）会删 lock，但**闪退那次恰好没走到
`onDestroy`** ⇒ 文件留下 ⇒ 于是闪退那一次本该是唯一该弹的场景，
之后**每一次正常启动**也弹 ⇒ 提示毫无信息量。

### 修法：判据换成独立的 `crash.flag`（不会被自己重写）
★ 关键洞察：**`run.lock` 的「存在」本身没有意义**（每次都被重写），
它真正的语义是「本次退出时**是否删掉了它**」—— 需要一个**独立载体**。

三步闭环（缺一不可）：

| 步骤 | 位置 | 作用 |
|---|---|---|
| ① 启动时**读** | `initLogFile` | 存在 = 上次闪退（并取现场） |
| ② 启动末尾**写** | `initLogFile` 尾部 | 「本次已起来」 |
| ③ 正常退出**删** | `markCleanExit` | 「本次正常退了」 |

另加 `crashTipShown` 一次性守卫（切前台恢复共享会**再跑一次** `autoStart`）。

⚠️ **刻意没删提示本身**：它是**真机唯一的排障通路**（没 hdc 时崩溃现场只能靠
「复制日志」带走，5.0.49 的原意）。要修的是「它该只在真闪退后出现一次」。

### 沉淀
**「标记文件存在」当判据前，先问「它会不会被自己重写」** ——
**一个「存在即真」的标记，若本次运行会写它，它就永远为真。**
判据：这个文件的语义是「存在」还是「上次没被清理」？后者必须有独立载体。

### 过程
补丁一次通过（dry-run 复核了 flag 的读/写/删三步配平）。
⚠️ 改脚本时自己踩了「改名改一半」的坑（`OLDS2` 变成混合体、锚点命中 0）——
**heredoc 里的转义把我搅了** ⇒ 又一次印证：**heredoc 适合执行，不适合编辑**；
改名/改多行块一律用 Edit 工具。

**产物**：`LANShare-5.1.10.hap`（2,508,580 B，已推手机 Download）；commit `dfdd4d3` + tag `v5.1.10`。

**待 vivi 复测**：① 正常启动**不再**弹闪退提示；
② 真闪退后启动**弹一次**（下次正常启动不重复弹）；
③ 切前台恢复共享**不重复弹**；
④ 「复制日志」仍可用（排障通路）；⑤ 5.1.9 的「视频」文字角标正常。
'''
    io.open(LOG, 'w', encoding='utf-8', newline='\n').write(s3)
    print('OK LOG -> %d' % len(s3))
