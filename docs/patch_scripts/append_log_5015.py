# -*- coding: utf-8 -*-
"""把 5.0.15 的记录追加到工作区日志（追加型写入，带哨兵判重）。"""
import sys

LOG = r"E:\lanshare项目\.workbuddy\memory\2026-10-01.md"
SENT = "## 15:26 — LANShareV5 5.0.15"

TEXT = '''
## 15:26 — LANShareV5 5.0.15（多选返回 / 删除按钮 / 接收更流畅 / 设备下线提速）

vivi 15:13 真机反馈（机上 5.0.14）四项，全部落地、构建并推送。

### 1. 多选态按返回直接回桌面

`Index.ets` 从未实现 `onBackPress()` —— 系统返回的默认行为就是**退出应用**。
新增 `onBackPress(): boolean`：多选态 → `exitFileSelect()`（留在文件页）；
二维码 / 发文件弹窗 → 关弹窗；都没有才 `return false` 交还系统。
**返回语义 = 先退掉最上层临时状态。**

### 2. 文件页删除按钮加回来

行内恢复「删除」（红字 `#E84026` / 浅底 `#FDECEA`），落在第二行右侧；长按多选保留。
5.0.13 去掉它的原因（文件名与按钮同行被挤扁）已由同版的 Column 两段式布局解决，
所以加回第三个按钮不会复现。

### 3. 接收更流畅

- **主因**：`onSnapshot` 签名比较里剔除 `connections` / `webRequests` /
  `onlineDevices` / `knownDevices` —— `connections` 在接收期高频变化
  （16 条分片连接反复建立/关闭），而界面根本不渲染它，放进签名等于
  每次「有分片连上」都触发**整页重建**。剔除后接收期整页重建 → **0 次/秒**。
- `DEC_SLICE` 512KB → 256KB，`UI_YIELD_BUDGET` 16ms → 12ms。
- 天花板说明：单线程 + 逐字节 JS 解密（`FileCrypto.decData`），再快只能上 TaskPool，本轮不做。

### 4. 设备下线 ~10s → 2~3s（本轮重点：判死模型整个换掉）

- **旧模型从未成立**：单播探活 → 对端回包 → RTT ≤ 500ms → 信任分 +1 → 攒够 3 次才快速判死。
  真机上对端（1.35 平板）**不理 `UDP_GET_DEVICES`**，只按自己的周期广播 → RTT 判据命不中 →
  信任分永远 0 → 一直走 `DEVICE_OFFLINE_MS` = 8s 兜底 → 用户看到「十秒左右」。
- **新模型：TCP 连接复核**（确定性事实，不依赖对端应用层行为）。
  向对端文件端口 5856 建一次连接，**不发任何字节**就关闭
  （发魔数会被对端分流逻辑引到私有协议分支，等于造一条半截握手）。
  成功 = 在；立即 RST = 服务已停；SYN 超时 = 不在。
- 参数：`DEVICE_PROBE_QUIET_MS` 2000→1200、`DEVICE_PROBE_RETRY_MS` 1000→1500、
  `DEVICE_TCP_PROBE_TIMEOUT_MS`=1000、`COOLDOWN`=700、`MISS_LIMIT`=2、`VERIFY_MAX_MISS`=3。
  `DEVICE_PROBE_DEADLINE_MS` / `DEVICE_PROBE_MAX_RTT_MS` / `DEVICE_PROBE_TRUST` 及
  `probePendingAt` / `probeTrust` / `noteProbeAnswer` **全部删除** ——
  UDP 探活降级为「让愿意应答的设备顺便刷新在线时间」，不再参与判死。
- **安全阀**（防列表闪烁）：只有「曾经 TCP 复核成功过」的设备才允许用失败判死；
  连续 2 次失败才判死；任何一次成功、或收到它任意一个 UDP 包即清零失败计数。

### 结果

- 版本 5.0.14 → **5.0.15**；全量重建 **BUILD SUCCESSFUL**（49s 467ms，33/33 任务）。
- 产物 2031443 B，sha256 `e2b3d7f093ee2e4e00a87fdf9b5b9e3bcb89e3fdb59f4d1b488ddfe399ace41a`；
  **已推送**（build.cmd 自动推，USB + WiFi 双通道）→ `Download/LANShareV5-5.0.15.hap`。
- 编入验证：解包 `ets/modules.abc`，`onBackPress`×2 / `TCP 复核失败` /
  `关闭探活套接字失败` / `判定下线` / `DEVICE_TCP_PROBE_MISS_LIMIT` 均命中。

### 踩坑（新形态：区间少覆盖一行）

补丁脚本把 `import` 区写成 `(25,27)`，真实区段是 **25~28 四行** →
删掉了 `common` / `fileIo`、留下重复的 `deviceInfo` → 20 个 `10505001` 编译错误。

两道已有保险都没拦住：`expect` 关键字（行号没偏移，是区间本身划小了）、
括号增量一致（`import { X }` 的括号成对，增量相同）。

→ **教训：区间边界要从语法块起止推，不能靠"看起来差不多"。**
（同一脚本里 `dropDevice` 那次是同一种错：区间包住整个方法，替换块却只写了前半段。）
三处脚本已归档到 `docs/patch_scripts/`。

### 技能沉淀

- `harmonyos-arkui-ui-pitfalls`：新增 **第二十节**（`onBackPress()` 返回键拦截；
  「返回 = 先退最上层临时状态」的优先级写法；未实现时默认是退出应用）。
- `harmonyos-tcp-socket-server`：新增 **坑十九**（用 TCP 连接做对端存活判定：
  「连得上就是在」的确定性凭据 + 安全阀 + 只建连不发字节的原因 +
  为什么 UDP 探活在真实对端上靠不住）。
'''


def main():
    s = open(LOG, "r", encoding="utf-8", newline="").read()
    if SENT in s:
        print("[SKIP] 5.0.15 记录已存在")
        return 0
    assert s.count(SENT) == 0
    open(LOG, "a", encoding="utf-8", newline="").write(TEXT)
    print("[OK] 已追加 5.0.15 记录，日志现 %d 字符" % (len(s) + len(TEXT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
