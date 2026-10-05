# -*- coding: utf-8 -*-
"""5.0.15 第二批：仅更新注释 / 变更记录（不改任何逻辑）。行号区间替换，幂等。"""
import sys

BASE = r"E:\lanshare-harmony\LANShareV5\entry\src\main\ets"


def load(path):
    raw = open(path, "r", encoding="utf-8", newline="").read()
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def save(path, text, crlf):
    open(path, "w", encoding="utf-8", newline="").write(
        text.replace("\n", "\r\n") if crlf else text)


def splice(text, a, b, new_block, expect, tag):
    lines = text.split("\n")
    if not (1 <= a <= b <= len(lines)):
        raise AssertionError("%s: 行号越界 %d-%d" % (tag, a, b))
    seg = "\n".join(lines[a - 1:b])
    if expect not in seg:
        raise AssertionError("%s: 区间 %d-%d 未找到 %r\n%s" % (tag, a, b, expect, seg[:400]))
    if (seg.count("{") - seg.count("}")) != (new_block.count("{") - new_block.count("}")):
        raise AssertionError("%s: 区间 %d-%d 括号增量不一致" % (tag, a, b))
    return "\n".join(lines[:a - 1] + new_block.split("\n") + lines[b:])


# ---------------- LanConfig：DEVICE_OFFLINE_MS 注释 ----------------
CFG_NEW = '''   *       对端主动下线（cmd 1003）→ 立刻消失；
   *       对端关掉 App / 强杀 / 拔电（**TCP 复核连得上**的设备）→ **约 2~3s** 消失；
   *       其余情况 → 本值兜底（配合 1s 巡检，≈ 8~9s）。'''

# ---------------- Index：变更记录表 ----------------
IDX_CHANGELOG_NEW = ''' * ## 2026-10-01 第七轮（5.0.15，vivi 真机实测）
 * | 诉求 | 落法 |
 * |---|---|
 * | 多选后返回不该回桌面 | 补 `onBackPress()`：多选态 → 取消多选；二维码 / 发文件弹窗 → 关弹窗；都不是才交还系统。**返回的语义是「先退掉最上层临时状态」** |
 * | 把文件页的删除按钮加回来 | 行内恢复「删除」（红字浅底，落在第二行右侧）；长按多选继续保留 —— 删一个点按钮、删一批用多选 |
 * | 接收还是不够流畅 | ① `snapshot` 签名**剔除** `connections` / `webRequests` / `onlineDevices` / `knownDevices` —— 前两个在接收期高频变化（16 条分片连接反复建立/关闭），而界面上根本不渲染它们，放签名里等于让每次「有分片连上」都触发**整页重建**；② 解密切片 512KB → **256KB**、让帧预算 16ms → 12ms |
 * | 对方关掉 App 十秒左右才显示下线 | **换掉判死模型**：UDP「信任分」在本机与 1.35 平板之间**从未攒够过**（对端不理 `UDP_GET_DEVICES`，偶尔命中的那次也只是撞上它自己的周期广播、RTT 超判据），实际一直走 8s 兜底。改成 **TCP 复核** —— 向对端文件端口 5856 建一次连接（**不发任何字节**就关，免得被引到私有协议分支），连不上连续 2 次即判死。预期 **2~3s** 消失（见 `LanConfig.DEVICE_TCP_*`） |
 *
 * ## 2026-10-01 第六轮（5.0.14）
 * | 诉求 | 落法 |
 * |---|---|
 * | 首页的网址显示不全了 | 上一版把「复制 / 二维码」与网址放同一行，`layoutWeight(1)` 只拿到剩余宽度（约 200vp）放不下 26 字符的地址。改为按钮上移到标题行，**网址独占整行铺满** |
 * | 检测设备下线还是不够快 | ① 收到 `UDP_DEVICES_OFF_LINE(1003)` 立刻移除（原版 Android 就是这么做的，smali `LANService.smali:14116`；我们此前只发不收）；② 对安静 1.2s 的设备发 **UDP 单播探活**；③ `SCAN_TIME` 5s→3s |
 * | 接收文件时界面卡顿、切 Tab 卡好几秒 | ① 进度从 `snapshot` 拆成独立 `@State`（`tText`/`tPercent`），10Hz 的进度刷新不再触发**整页重建**；② `snapshot` 其余字段走签名比较，没变就不赋值；③ 接收循环里同步逐字节解密切片 + 预算**让帧给 UI**（`V5Transfer.yieldFrame`） |
 * | 多选后取消保存，不该退出多选 | `ExportService.saveMany` 改返回 `SaveOutcome`（带 `cancelled`）；取消时保留勾选与多选态，原样停住等用户再点一次 |'''

# ---------------- Index：fileSelectMode 注释 ----------------
IDX_SELECT_DOC_NEW = '''   * 为什么要有它：长按进多选后可以一次另存 / 删除一批，比一个个点确认快得多。
   * ⚠️ 5.0.13 曾把行内「删除」按钮整个去掉，5.0.15 按 vivi 要求**加回来了** ——
   *    现在文件名独占一行、按钮都在第二行，三个按钮也不会再把它挤扁。
   *    两种删法并存：删一个点行内按钮，删一批长按多选。'''

PATCHES = [
    (BASE + r"\core\LanConfig.ets", "约 2~3s", [(101, 102, CFG_NEW, "对端被强杀")]),
    (BASE + r"\pages\Index.ets", "第七轮（5.0.15", [
        (200, 203, IDX_SELECT_DOC_NEW, "为什么要有它"),      # ⚠️ 必须按行号降序
        (70, 76, IDX_CHANGELOG_NEW, "第五轮"),
    ]),
]


def main():
    staged = []
    for path, sentinel, items in PATCHES:
        text, crlf = load(path)
        if sentinel in text:
            print("[SKIP] 已更新: %s" % path)
            continue
        for a, b, block, expect in items:
            text = splice(text, a, b, block, expect, path)
        staged.append((path, text, crlf))
    if not staged:
        print("[NOTHING] 注释已是最新")
        return 0
    for path, text, crlf in staged:
        save(path, text, crlf)
        print("[OK] %s" % path)
    print("[DONE] 注释更新完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
