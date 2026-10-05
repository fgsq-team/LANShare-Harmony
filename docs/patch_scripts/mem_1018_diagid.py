# -*- coding: utf-8 -*-
import io
P = r'E:\lanshare项目\.workbuddy\memory\2026-10-03.md'
s = io.open(P, encoding='utf-8').read()
if '## 10:18 诊断版没被装上' in s:
    print('ALREADY')
    raise SystemExit(0)

ADD = r'''

## 10:18 诊断版没被装上 —— 「测试无效」其实是**测错了版本**（重要教训）

vivi 让我看日志。拉 `files/` 才发现**根本没有 `ui_log.txt`** ⇒ 应用没跑过诊断版。
`bm dump` 显示装的是 **`versionName: 5.1.13`（正式版）**，
而 `Download/` 里躺着的是 `LANShare-5.1.13-diag.hap` ⇒ **装的是旧正式版，不是诊断版**。

### 根因：**文件名带 `-diag` 后缀，但 `versionName` 没带**
我出诊断版时只改了**文件名**（`LANShare-5.1.13-diag.hap`），
`app.json5` 里 `versionName` 仍是 `"5.1.13"` ⇒ **关于页和 `bm dump` 都看不出是诊断版**。
⇒ 版本号必须能自证是诊断版，否则「装错版本」会伪装成「优化无效」，
白白多花一轮排查（这正好撞上「连错两轮就改用观测」的纪律）。

### 定为铁律（诊断版必须自带身份标识）
1. `versionName` 加 `-diag` 后缀（会显示在关于页，`bm dump` 查得到）
2. **`versionCode` 用独立段 `5000199`**（-99 表示诊断通道，永不与正式版冲突）
3. **文件名用 `LANShare-DIAG-<ver>.hap`**（后缀前置，一眼区分，不靠 `-diag` 尾巴）
4. 推完后**必须用 `bm dump` 确认装的是哪一版**，不能只看 `ls -l` 有文件

### 顺带
- vivi 本轮对端是**平板**，网页能到 **55MB/s**（车机时是 40）
  ⇒ 差距从 30 vs 40 拉大到 **30 vs 55**，更能说明是**协议/并发**问题而非对端存储。
- 旧文件 `LANShare-5.1.13-diag.hap` 删不掉（`hdc file rm` 参数不对，
  打印了 hdc 帮助 ⇒ 该子命令不存在/参数名有误）⇒ 需查 `hdc file --help`；
  在此之前靠**新文件名 `LANShare-DIAG-*` 前缀**来避免误装。

### 下一步（待 vivi 装完诊断版）
装 `LANShare-DIAG-5.1.13.hap` → 发一个 ≥200MB 文件 → 我拉 `ui_log.txt` 读 `[DIAG]` 行。
'''

s = s.rstrip('\n') + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
b = io.open(P, 'rb').read()
print('OK -> %d chars  CRLF=%d  坏字符=%d' % (len(s), b.count(b'\r\n'), s.count(chr(0xFFFD))))
