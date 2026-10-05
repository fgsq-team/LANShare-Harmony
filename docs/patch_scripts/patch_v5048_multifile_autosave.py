# -*- coding: utf-8 -*-
"""
5.0.48：
 A. 【根因修复】文件级收尾补终态 2（多项发送从第 2 项起卡死）
 B. 【诊断】「自动存相册」链路每步打 UI 日志 + 失败弹 toast

A 的证据链（全部来自本仓库既有取证，非推断）：
  · receiveSegment 尾部（V5Transfer.ets ~1308-1315）早就写明：
      「收完一片回**两个**字节：先 5 = FS_NEXT，再 2 = FS_END。
        ⚠️ 只回 5 是不够的：1.35 的发送端读到 5 会 goto :cond_4 **再读一个字节**，
        于是它要一直阻塞到我们 close 连接（read 返回 -1）才收尾。」
    —— 但这条修复只加到了**片级(1110)接收**，**文件级(1101)接收**一直是「只回 5」。
  · 1.35 接收端文件收完时也写 2（dump_lo2j.txt 375-376：const/4 v5, 2; write(I)）。
  · 真机症状完全吻合：单项「看着成功」（对端靠连接关闭 EOF 收尾）；
    多项则第 1 项收满后，对端阻塞在「等第二个字节」，第 2 项永远等不到数据
    （60s 超时、0 字节）。

B 的目的：5.0.47 加了接收链 UI 日志，但「自动存相册」失败时仍只写 hilog，
  用户侧看不到任何信息。本版把该链路每步（入队/解析/弹框/返回/异常）打进 UI 日志，
  并在异常时弹 toast —— 下一轮真机日志即可精确定位「弹窗没出现」的原因。
"""
import io
import sys

BASE = r'E:/lanshare-harmony/LANShareV5'
VT = BASE + '/entry/src/main/ets/service/V5Transfer.ets'
LS = BASE + '/entry/src/main/ets/service/LanService.ets'
PAGE = BASE + '/entry/src/main/ets/pages/Index.ets'
APP = BASE + '/AppScope/app.json5'

SENTINEL = '5.0.48'


def load(p):
    return io.open(p, encoding='utf-8', newline='').read()


def save(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def rep(s, tag, old, new, p=''):
    n = s.count(old)
    assert n == 1, f'[{tag}] {p} 锚点出现 {n} 次（期望 1）'
    return s.replace(old, new)


def patch_vt(s):
    old = (
        "        const ack: Uint8Array = new Uint8Array([ok ? LCmd.FS_NEXT : LCmd.FS_BREAK]);\n"
        "        await chan.send(ack);\n"
        "        if (!ok) {"
    )
    new = (
        "        const ack: Uint8Array = new Uint8Array([ok ? LCmd.FS_NEXT : LCmd.FS_BREAK]);\n"
        "        await chan.send(ack);\n"
        "        // 5.0.48：文件级收尾也必须再补一个终态 2（FS_END / RECV_OK），与**片级收尾**\n"
        "        //   完全一致（见 receiveSegment 尾部：同样是「先 5 再 2」）。\n"
        "        //   1.35 接收端文件收完时也写 2（取证 dump Lo2/j）；而 1.35 发送端读到 5 后\n"
        "        //   **还会再读一个字节** —— 只回 5 时它一直阻塞到我们关连接为止。\n"
        "        //   真机症状：单项「看着成功」（靠关连接收尾），多项从第 2 项起永远等不到\n"
        "        //   数据（第 1 项收满后第 2 项 60s 超时、0 字节）—— 正是本行缺失导致。\n"
        "        if (ok) {\n"
        "          await chan.send(new Uint8Array([LCmd.FS_END]));\n"
        "          if (onLog) {\n"
        "            onLog(`v5 \"${item.name}\" 收尾已回 5+2（FS_NEXT+FS_END），可继续下一项`);\n"
        "          }\n"
        "        }\n"
        "        if (!ok) {"
    )
    return rep(s, 'file_end_ack', old, new, 'V5Transfer')


def patch_ls(s):
    old = (
        "  private pushLog(line: string): void {\n"
        "    const ts: string = new Date().toTimeString().substring(0, 8);\n"
        "    this.logRing.push(`[${ts}] ${line}`);\n"
        "    if (this.logRing.length > 200) {\n"
        "      this.logRing.shift();\n"
        "    }\n"
        "  }"
    )
    new = old + (
        "\n\n"
        "  /**\n"
        "   * 5.0.48：「收到图片/视频自动存相册」链路的诊断入口（由 Index 页面层调用）。\n"
        "   * 这条路之前失败时只写 hilog，真机（无线调试不可用）抓不到，只能靠猜。\n"
        "   * 现在每步都进 UI 日志。\n"
        "   */\n"
        "  logAuto(msg: string): void {\n"
        "    this.pushLog(`[相册] ${msg}`);\n"
        "    this.emit();\n"
        "  }"
    )
    return rep(s, 'logAuto', old, new, 'LanService')


def patch_page(s):
    # 1) autoSaveNewMedia 入口：调整早退顺序 + 打日志
    old = (
        "  private autoSaveNewMedia(oldCount: number): void {\n"
        "    if (!this.autoAlbum) {\n"
        "      return;\n"
        "    }\n"
        "    if (oldCount >= this.chat.length) {\n"
        "      return;\n"
        "    }"
    )
    new = (
        "  private autoSaveNewMedia(oldCount: number): void {\n"
        "    if (oldCount >= this.chat.length) {\n"
        "      return;\n"
        "    }\n"
        "    // 5.0.48：这条链路每步都打 UI 日志 —— 之前弹窗没出现时真机上什么都看不到\n"
        "    this.service.logAuto(`新消息 ${oldCount} -> ${this.chat.length}，自动存相册开关=${this.autoAlbum}`);\n"
        "    if (!this.autoAlbum) {\n"
        "      return;\n"
        "    }"
    )
    s = rep(s, 'asm_entry', old, new, 'Index')

    # 2) 入队：打日志
    old = (
        "      this.autoSavePending.push(m.id);\n"
        "    }\n"
        "    if (this.autoSavePending.length === 0) {\n"
        "      return;\n"
        "    }"
    )
    new = (
        "      this.autoSavePending.push(m.id);\n"
        "      this.service.logAuto(`入队待存相册：「${m.content}」(id=${m.id})`);\n"
        "    }\n"
        "    this.service.logAuto(`待存队列共 ${this.autoSavePending.length} 项`);\n"
        "    if (this.autoSavePending.length === 0) {\n"
        "      return;\n"
        "    }"
    )
    s = rep(s, 'asm_queue', old, new, 'Index')

    # 3) flushAutoSave：解析不出路径 / 准备弹框
    old = (
        "    if (paths.length === 0) {\n"
        "      return;\n"
        "    }\n"
        "    this.autoSaveBusy = true;"
    )
    new = (
        "    if (paths.length === 0) {\n"
        "      this.service.logAuto(`队列 ${this.autoSavePending.length} 项暂未解析出沙箱路径（等文件落盘后再试）`);\n"
        "      return;\n"
        "    }\n"
        "    this.service.logAuto(`准备弹存相册确认框：${paths.length} 个文件`);\n"
        "    this.autoSaveBusy = true;"
    )
    s = rep(s, 'flush_paths', old, new, 'Index')

    # 4) 确认框返回
    old = (
        "      const uris: string[] = await helper.showAssetsCreationDialog(srcUris, cfgs);\n"
        "      if (uris.length === 0) {"
    )
    new = (
        "      const uris: string[] = await helper.showAssetsCreationDialog(srcUris, cfgs);\n"
        "      this.service.logAuto(`确认框返回 ${uris.length} 个 URI（提交 ${srcUris.length} 个）`);\n"
        "      if (uris.length === 0) {"
    )
    s = rep(s, 'dialog_ret', old, new, 'Index')

    # 5) 外层 catch：UI 日志 + toast（把静默失败变成可见）
    old = (
        "    } catch (e) {\n"
        "      const err: BusinessError = e as BusinessError;\n"
        "      Log.w(TAG, `自动存相册失败: ${err.code} ${err.message}`);\n"
        "      failed = true;\n"
        "    } finally {"
    )
    new = (
        "    } catch (e) {\n"
        "      const err: BusinessError = e as BusinessError;\n"
        "      Log.w(TAG, `自动存相册失败: ${err.code} ${err.message}`);\n"
        "      this.service.logAuto(`自动存相册失败：${err.code} ${err.message}`);\n"
        "      this.toast(`自动存相册失败：${err.message}`);\n"
        "      failed = true;\n"
        "    } finally {"
    )
    s = rep(s, 'catch_toast', old, new, 'Index')
    return s


def main():
    if SENTINEL in load(VT):
        print('ALREADY APPLIED')
        return

    vt = patch_vt(load(VT))
    ls = patch_ls(load(LS))
    pg = patch_page(load(PAGE))

    # 全部校验通过后再统一落盘
    save(VT, vt)
    save(LS, ls)
    save(PAGE, pg)

    a = load(APP)
    oldv = '"versionCode": 5000047,\n    "versionName": "5.0.47",'
    newv = '"versionCode": 5000048,\n    "versionName": "5.0.48",'
    assert a.count(oldv) == 1, f'app.json5 版本锚点 {a.count(oldv)} 次'
    save(APP, a.replace(oldv, newv))

    print('OK: 5.0.48 已应用（文件级收尾补 +2 + 自动存相册全链路 UI 日志 + 版本号）')


if __name__ == '__main__':
    main()
