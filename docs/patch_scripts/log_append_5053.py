# -*- coding: utf-8 -*-
"""追加 5.0.53 段到当日工作日志。幂等：哨兵判重。"""
import io, sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
SENTINEL = '### 14:50 5.0.53'

ADD = '''

### 14:50 5.0.53 — 按 vivi 给的方案：**接收多个图片/视频 → 每个一条消息**（治本）

**vivi 真机反馈**：5.0.52「多张图片删除第一张，其他的也不会跳转到相册了」。
并直接给了方案：一次接收多个图片/视频时每个媒体一条记录；文件仍合并成一条；
另存到本地后也把沙箱副本删掉。

**诊断**：5.0.52 的 `消息id#媒体序号` 是「在一条消息里硬塞 N 个槽位」——**治不彻底**。
气泡只有**一个**点击入口（只指向第 1 张），用户根本点不到第 2 张；删掉第 1 张把那个
唯一入口的判定摘掉后，整批就都不再跳相册了。根因是**记账粒度**跟「最细的可变化单位」没对齐。

**修法**：在**生成消息**那一步就把批量媒体拆开（`LanService.appendFileChat`）——
每条消息 `id` 天然唯一 ⇒ 相册索引 / 缩略图文件名 / 旋转角 / ForEach key 全部自动正确，
**下游一行都不用改**。边界：只拆**接收**方向；只有**整批全是媒体**才拆（混合批保持一条，
否则像收了两次）；「是不是媒体」的判定**全局唯一**（`LanService.isMediaFileName` 为真源，
`Index.isMediaName` 改为委托它，避免「拆了却没缩略图」）。

**改动**：
- `LanService.ets`：新增 `appendFileChat` / `allMedia` / `static isMediaFileName`；
  `onTransferReport` 与 `onWebUploadEnd` 改走它（网页端上传顺带补上了 `names`，以前只传合并文案，
  所以网页上传的图**一直没有缩略图**）。
- `ExportService.ets`：`SaveOutcome` 增 `savedPaths: string[]`（只收**成功**的那些）。
- `Index.ets`：`isMediaName` 委托；`saveAsFile` / `batchSaveSelected` 在另存成功后
  **删掉沙箱副本**（与 5.0.38 起「存相册后删沙箱」统一口径）；取消/失败一律不动。

**构建踩到的新坑（已归档进 skill `harmonyos-hvigor-cli-build`）**：
`spawn java ENOENT`（00308018）这次**不是没装 JDK** —— `java.exe` 明明在。
真因：Git Bash 里 `export PATH="C:/Users/...:$JH/bin:$PATH"` 中的 **`C:` 被 MSYS 当成
POSIX 的 `:` 分隔符**，PATH 被切成 `C;C:\\...\\PortableGit\\...\\Users\\...`，
Windows 解析不出 java。`env PATH="a;C:/b"` 这种显式分号写法**同样不行**（PATH 是特殊变量）。
**修法**：`unset MSYS_NO_PATHCONV MSYS2_ARG_CONV_EXCL` + 用纯 MSYS 路径 `/c/...` 冒号拼接。
**判据**：`node -e "console.log(process.env.PATH.split(';').filter(s=>/java/i.test(s)))"`
应打印反斜杠 + 分号形态。

**产物**：`E:\\lanshare-harmony\\LANShare-5.0.53.hap`（2,366,841 B）；
`BUILD SUCCESSFUL in 14s 998ms`；解包 `modules.abc` 按 **UTF-8 字节**搜到
`沙箱副本已删除` / `个沙箱副本` / `已清理` / `isMediaFileName` / `appendFileChat`（⚠️ 中文串要按
UTF-8 字节搜，用 latin-1 映射搜不到 —— 上一轮差点误判成「没编进去」）；
`module.json` 报 5.0.53 / 5000053。commit `613e37f`，tag `v5.0.53`，夸克网盘
`夸克网盘/来自：WorkBuddy`。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.count('### 13:40 5.0.52 交付与知识归档') == 1, '找不到 5.0.52 收尾小节'
s2 = s + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 日志已追加，%d -> %d' % (len(s), len(s2)))
