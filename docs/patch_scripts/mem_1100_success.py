# -*- coding: utf-8 -*-
import io
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if '## 11:00 ★★ 提速成功 52.9MB/s' in s:
    print('ALREADY')
    raise SystemExit(0)

ADD = r'''

## 11:00 ★★★ 提速成功：**35.7 → 52.9 MB/s**（+48%），真机实测确认

vivi 装 5.1.17 后实测，日志（`hilog` 的 V5Transfer 行）：
```
v5 已发送 launchermap_3.9.151-20260930.apk (677501607 B, 647 块, 12219ms, 52.9MB/s, 块均 18.9ms)
```

| | 改前（5.1.13/5.1.14） | 改后（5.1.17） | 变化 |
|---|---|---|---|
| 块均耗时 | 28.0 ms | **18.9 ms** | **-32%** |
| 吞吐 | 35.7 MB/s | **52.9 MB/s** | **+48%** |
| 网页（对端） | — | ~55-60 MB/s | **已接近** |

`[DIAG]` 分段（每 1MiB 块）：`read=0~1ms / enc=0 / copy=0 / other=0`，
`send` 从 26-28ms 降到 **10~18ms**（个别块 37ms）。
⇒ **确认：瓶颈就是显式 SO_SNDBUF 关闭了内核 TCP 自动调优。** 判断正确。

## 另一件事：网页上传「坏了」是浏览器问题，与代码无关
vivi 装回 **5.1.12** 后网页仍发不了文件 ⇒ 排除我的改动（5.1.12 早于我的全部改动）。
**换浏览器就成功了** ⇒ 纯浏览器问题（缓存/兼容/插件）。

### ★★ 后端已用探针独立证明是好的
`tests/live-probe/probe_upload.mjs`（新增，模拟浏览器 multipart 上传）：
| 测试 | 结果 | 耗时 |
|---|---|---|
| 3MB | **200 OK** | 257ms |
| **100MB** | **200 OK** | 5.4s |
服务端 `ui_log` 里当时只有 `POST /initConfig`、**没有任何 `/uploadFile`** ⇒
**浏览器压根没发请求**，不是后端拒收。

★ **排查工具**：`probe_upload.mjs` 用法
`PROBE_SIZE=<字节> node probe_upload.mjs <host> <port>`
⇒ 以后网页上传类问题，先跑这个探针：**200 OK 就是后端没问题，直接查浏览器**。
路径 `LANShare-PC-main/LANShare-PC-main/tests/live-probe/probe_upload.mjs`。

## 未结：对端「接受失败」
同一文件在 10:54:39 与 10:55:00 **发了两次**（10:54 与 10:55 各 646.1MB），
鸿蒙侧两次都「647 块全发完、无任何错误」⇒ 失败提示来自**对端（DBY-W09 安卓）**。
最可能：**同名文件重复**（安卓侧重名会拒绝或自动改名）⇒ 下次测速请用**不同文件名**。
'''
s = s.rstrip('\n') + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count(chr(0xFFFD))))
