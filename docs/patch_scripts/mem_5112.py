# -*- coding: utf-8 -*-
"""5.1.12 的取舍写进 MEMORY + 今日日志 + 版本编年。"""
import io

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
LOG = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
VER = r'E:\lanshare项目\.workbuddy\memory\VERSION_HISTORY.md'

s = io.open(MEM, encoding='utf-8').read()
if '5.1.12' not in s:
    ANCHOR = '7. ★ **`hdc` 无设备时交付不停**（夸克网盘）'
    assert s.count(ANCHOR) == 1, s.count(ANCHOR)
    ADD = '''4t. ★★★★★★★★★★ **用户说「把 X 提示删了」——先分清 X 是「UI」还是「能力」**（5.1.12）。
    vivi 要求删「检测到上次闪退」的 toast（升级后必现，纯噪声）。
    ★ 但 `crashTail`（崩溃前 150 行挂日志列表最前）+ `ui_log.txt.1` 存档
    是**真机唯一的排障通路**（用户没 hdc，5.0.49 的原意）⇒ 删掉 = 下次真闪退**盲修**。
    ✅ 正确处置 = **只删 UI，能力全留**：
      toast ⇒ 改成**只打一行日志**（用户界面干净，我需要时仍能从日志看到）；
      顺带删掉**只为该 toast 服务的字段**（`crashTipShown`）；`pushLog` 那条**保留**
      （它在**日志页**不是弹窗）。
    ★★★ **通则（本项目最容易犯的错）**：
      **「提示」与「取证」是两件事**。提示是 UI，取证是能力。
      删提示前先问「**这条信息背后的数据/动作还在吗**」——
      还在 ⇒ 只删 UI；不在 ⇒ 才是真的删功能（要跟用户确认代价）。
    ⚠️ 反向自保：删完要在**代码注释里写明「检测机制全部保留」**，
      否则下一个（包括我自己）看到「提示删了」会以为「检测也删了」⇒ 下次闪退变盲修。
    ★ 附：为什么升级后必现 —— `run.lock` / `crash.flag` 在 `filesDir` 里，
      **升级 HAP 时可能被系统清理/重建** ⇒ 每次升级后首次启动都会命中旧状态。
'''
    s = s.replace(ANCHOR, ADD + ANCHOR, 1)
    assert '5.1.12' in s and chr(0xFFFD) not in s
    io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
    print('OK MEMORY -> %d' % len(s))
else:
    print('MEMORY 已有 5.1.12，跳过')

s2 = io.open(VER, encoding='utf-8').read()
if '5.1.12' not in s2:
    s2 = s2.rstrip('\n') + '''

## 5.1.12（2026-10-02 22:09）
- **删掉「检测到上次闪退」的 toast**（vivi 反馈：每次升级后打开都提示一次，
  因为 `run.lock`/`crash.flag` 在 `filesDir` 里，**升级 HAP 时可能被清理/重建**）。
- ★ **只删 UI，检测与取证全部保留**：toast ⇒ 改为**只打一行日志**；
  `crashTail`（崩溃前 150 行挂日志最前）+ `ui_log.txt.1` 存档 +
  「复制日志」入口**一个都不动**（真机唯一排障通路，删了下次闪退只能盲修）。
'''
    io.open(VER, 'w', encoding='utf-8', newline='\n').write(s2)
    print('OK VERSION_HISTORY -> %d' % len(s2))

s3 = io.open(LOG, encoding='utf-8').read()
if 'v5.1.12' not in s3:
    s3 = s3.rstrip('\n') + '''

## 22:09 v5.1.12 —— 删掉闪退提示（保留后台取证）

vivi：「把检测到闪退的提示删除了」——起因是**每次升级软件后打开都会提示一次**。

### 为什么升级后必现
`run.lock` / `crash.flag` 都在 `${ctx.filesDir}/` ⇒ **升级 HAP 时可能被系统清理/重建**
⇒ 每次升级后的首次启动都会命中旧状态。而用户什么都没做 ⇒ 纯噪声，
且会让人以为「这软件一更新就崩」。

### ★ 处置：只删 UI，检测与取证【全部保留】
`crashTail`（崩溃前 150 行挂日志列表最前）+ `ui_log.txt.1` 存档 +
「复制日志」入口 = **真机唯一的排障通路**（用户没 hdc，5.0.49 的原意），
删掉它 = 下次真闪退**完全无法取证**、只能盲修。

所以只做三件事：
1. 删 `autoStart` 里的 toast 分支 ⇒ 改为**只打一行日志**（界面干净，我仍能查）；
2. 删 `crashTipShown` 字段（只为该 toast 服务）；
3. `initLogFile` 的 `pushLog` 保留 ⇒ 它在**日志页**不是弹窗。

### ★★★ 沉淀（本项目最易犯的错）
**「提示」与「取证」是两件事。** 用户说「把 X 提示删了」时，
先问「**这条信息背后的数据/动作还在吗**」——
还在 ⇒ **只删 UI**；不在 ⇒ 才是真的删功能（要跟用户确认代价）。
⚠️ 删完要在**代码注释里写明「检测机制全部保留」**，
否则下一个（包括我自己）看到「提示删了」会以为「检测也删了」⇒ 下次闪退变盲修。

**产物**：`LANShare-5.1.12.hap`（2,511,367 B，已推手机 Download）；commit `eeaa063` + tag `v5.1.12`。
解包验证：旧 toast 文案与 `crashTipShown` **已不存在**；取证链路（新日志行 /
prevCrashed / crashFlag / logAuto / 复制日志 / run.lock）**全部完好**。

**待 vivi 复测**：① 升级后打开**不再**有任何闪退提示；
② 若真闪退，日志页仍能看到「检测到上次异常退出」+ 崩溃前现场；
③ 「复制日志」仍可用；④ 5.1.11 的清空/批量删除记账正常。
'''
    io.open(LOG, 'w', encoding='utf-8', newline='\n').write(s3)
    print('OK LOG -> %d' % len(s3))
