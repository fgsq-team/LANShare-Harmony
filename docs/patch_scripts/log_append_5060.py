#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""追加 5.0.60 工作日志（幂等：哨兵串命中即跳过）。"""
import io
import os
import sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
SENTINEL = '### 17:11 5.0.60 —— PC 连发失败【判据失效】+ EXIF 方向照片比例/方向错乱'

ENTRY = """

### 17:11 5.0.60 —— PC 连发失败【判据失效】+ EXIF 方向照片比例/方向错乱

**两个独立问题，都是「5.0.58 / 更早的修复只做了一半」。**

#### 问题 1：PC 连发多图，最后一项必然 60 秒超时失败

日志（17:00 那批 5 张）：
```
[17:00:15] v5 对端宣告：name=vivi ip=192.168.10.186 mode=2 ver=5
[17:01:17] v5 "IMG_0097.JPG"：数据块 1869453 B 读取失败（已收 4194280/6063733）
```
正好 60 秒、连接没断 ⇒ 又是「对端卡住不发」。**5.0.58 修的方向是对的
（PC 只读 N+1，所以收尾只回 `2`），坏的是判据**：5.0.58 用
「宣告 IP == 本机 IP」判 PC，而实测本机 `.146` / PC 宣告 `.186`（它自己）
⇒ **判据从未命中**，一直走 N+2 ⇒ 每文件多 1 字节 ⇒ 块级节流失效 ⇒ 狂发 ⇒
窗口压满 ⇒ PC 裸 `::send()` 部分返回被当硬错误 ⇒ `FS_CLOSE` 被当数据体 ⇒ 60s。

**判据为什么必然不可靠**（PC 源码 `LANShare.cpp:467-474`）：
`makeDataEnc(*p1, …)` 里的 `p1` 遍历的是 **PC 自己的设备列表**，
取「与目标同子网的某一台」——**可能是它自己、也可能是别的设备**。
⇒ 同帧里的 `devIp / devName / devMode` **三个字段天生不可靠**。

★ **可靠的是同帧的 `uniqueUuid`**：取自 `config.uniqueUUid`（`LANShare.cpp:117`），
是**对端自己的 UUID**，与 `p1` 无关；而本机发现表 `devices: Map<string, LanDevice>`
的 **key 正好就是它** ⇒ 反查得到**真实** devMode。WINDOWS/LINUX/MAC/WEB ⇒ 按 N+1。
兜底保守：查不到就按「非 PC」（退回 N+2，与现状一致）。

#### 问题 2：15 张里第 12 / 15 张「比例和方向都不对」

规律：13 张本地对照图里**只有 `IMG_0069.JPG` 的 EXIF orientation = 8**，
其余全 1 —— 与用户说的「第 12 张」**完全对上**（第 12 项 = IMG_0069）。

沙箱取证：把 `album_thumbs/c12-#0.jpg` 拉回逐像素比对 ⇒
它是 213×320（竖）但内容是**「原图旋转 180° + 拉伸」**，与正确朝向差 90°。

**校验为什么漏掉**：现有校验只看**横竖性**
（`wantTall === gotTall`），而 **90° 与 270° 都会翻转横竖性**
⇒ 转反了 90° 照样通过。

**修法**：不去猜 `createPixelMap({rotate})` 的语义（来回改过多轮），
而是**绕开物理旋转** —— `deg !== 0` 时直接走「复制原图」缓存（**保留 EXIF**），
显示层 `thumbOri(-1)` → AUTO 交给 `Image` 自己转。这条路与「弹窗那一刻显示沙箱原图」
是**同一条已验证正确**的路。绝大多数照片（deg=0）路径**完全不变**。

**产物**：`LANShare-5.0.60.hap` 2,449,596 B，sha256 `be4f0a6b…`；
commit `fbdff47` + tag `v5.0.60`；已推手机 `Download/LANShare-5.0.60.hap`，
夸克网盘 fileId `4833cbb8a7954431ab773b7012fb4f55`。
skill `harmonyos-tcp-socket-server` 第九节的判据**已被真机证伪**，已改写为
「用同帧 uniqueUuid 反查本机发现表」，并补了「身份类判据必须把输入打进日志」。
"""

d = os.path.dirname(P)
if not os.path.isdir(d):
    os.makedirs(d)
if not os.path.exists(P):
    io.open(P, 'w', encoding='utf-8', newline='\n').write('# 2026-10-02 工作日志\n')

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED')
    sys.exit(0)

assert '\r' not in s, '目标日志里有 CRLF'
s = s.rstrip('\n') + '\n' + ENTRY
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)

chk = io.open(P, encoding='utf-8', newline='').read()
print('OK: 已追加 5.0.60 日志')
print('  len:', len(chk), '| CRLF:', '\r' in chk, '| 段:', chk.count(SENTINEL))
