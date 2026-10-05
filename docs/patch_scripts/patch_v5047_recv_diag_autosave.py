# -*- coding: utf-8 -*-
"""
5.0.47：① V5 接收链关键事件接进 UI 日志（诊断「多张卡死」）② 修自动存相册只弹一次。

背景（vivi 2026-10-02 真机日志）：
  安卓 1.35 -> 鸿蒙发**单张**图片全部成功；发「2 项 / 3 项」的请求全部卡死：
  「发送请求（2 项）」后 47 秒无任何数据，最后对端超时断开 -> 「接收失败：<文件名>」。
  卡点在 FS_AGREE 之后的数据流（失败上报里能给出文件名 = 清单已读到），
  但关键证据（清单项 size/rem、块计数、readExactly 超时）**只在 hilog**，UI 日志看不到。

改动 A —— 诊断（V5Transfer）：
  receive()/recvBody() 加可选参数 onLog，LanService 传 pushLog 打到 UI 日志：
    - 清单第 i 项：type / size / name / rem
    - 已回 AGREE，等数据流
    - 每项开始收 / 收满等结束帧 / 结束（字节+片数）
    - 失败细分原因：读帧头超时(60s)/数据块超时/对端断开/非数据帧 cmd=?/长度异常/字节数不符

改动 B —— 自动存相册（Index，确定 bug）：
  B1. `flushAutoSave()`：`.then` 里 `busy=false` 之后**补一次 `flushAutoSave()`**。
      原时序：batch 的 finally（refreshReceived -> flushAutoSave，此时 busy 仍 true 被跳过）
      先于 `.then(busy=false)` 执行，之后无人再触发 -> 第一批评弹框期间入队的
      后续图片**永远不弹**（vivi 真机：只有第一次有弹窗）。
  B2. `autoSaveAlbumBatch()` 循环体 per-file try/catch：一张图 cacheThumb/copyTo
      抛异常不再中断整批。
  B3. 异常（catch）路径不再把整批评为「已处理」—— 留队等下一次 refreshReceived 重试；
      用户点取消（空数组）才结案，避免一次系统瞬时错误导致永久不弹。
"""
import io

VT = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/service/V5Transfer.ets'
LS = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/service/LanService.ets'
PAGE = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'
APP = r'E:/lanshare-harmony/LANShareV5/AppScope/app.json5'

SENTINEL = '5.0.47'


def load(p):
    return io.open(p, encoding='utf-8', newline='').read()


def save(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def rep(s, tag, old, new, p=''):
    n = s.count(old)
    assert n == 1, f'[{tag}] {p} 出现 {n} 次'
    return s.replace(old, new)


def patch_v5transfer(s):
    # 1) receive 签名加 onLog
    s = rep(s, 'sig_receive',
        "    storage: FileStorage,\n    onReport: TransferCallback\n  ): Promise<boolean> {",
        "    storage: FileStorage,\n    onReport: TransferCallback,\n"
        "    onLog?: (s: string) => void\n  ): Promise<boolean> {")

    # 2) 清单项日志 -> 同时打 UI 日志
    s = rep(s, 'item_log',
        "        items.push(it);\n"
        "        Log.i(TAG, `v5 清单项[${i}] type=${it.fileType} size=${it.length} name=${it.name} rem=${d.remaining}`);",
        "        items.push(it);\n"
        "        Log.i(TAG, `v5 清单项[${i}] type=${it.fileType} size=${it.length} name=${it.name} rem=${d.remaining}`);\n"
        "        if (onLog) {\n"
        "          onLog(`v5 清单[${i + 1}/${count}] type=${it.fileType} size=${it.length} \"${it.name}\" 帧内剩余=${d.remaining}`);\n"
        "        }")

    # 3) AGREE 已发
    s = rep(s, 'agree',
        "      await chan.send(V5Transfer.simpleFrame(LCmd.FS_AGREE));\n      const names: string[] = [];",
        "      await chan.send(V5Transfer.simpleFrame(LCmd.FS_AGREE));\n"
        "      if (onLog) {\n"
        "        onLog(`v5 已回同意（AGREE），等待 ${items.length} 项数据流…`);\n"
        "      }\n      const names: string[] = [];")

    # 4) 每项开始收
    s = rep(s, 'loop_head',
        "      let done: number = 0;\n      for (let i = 0; i < items.length; i++) {\n"
        "        const item: V5Incoming = items[i];",
        "      let done: number = 0;\n      for (let i = 0; i < items.length; i++) {\n"
        "        const item: V5Incoming = items[i];\n"
        "        if (onLog) {\n"
        "          onLog(`v5 开始收第 ${i + 1}/${items.length} 项 \"${item.name}\"（${item.length} B）`);\n"
        "        }")

    # 5) recvBody 签名加 onLog
    s = rep(s, 'recvbody_sig',
        "  private static async recvBody(\n    chan: TcpChannel,\n    item: V5Incoming,\n"
        "    encData: boolean,\n    storage: FileStorage,\n"
        "    onChunk: (got: number, size: number) => void\n  ): Promise<boolean> {",
        "  private static async recvBody(\n    chan: TcpChannel,\n    item: V5Incoming,\n"
        "    encData: boolean,\n    storage: FileStorage,\n"
        "    onChunk: (got: number, size: number) => void,\n"
        "    onLog?: (s: string) => void\n  ): Promise<boolean> {")

    # 6) recvBody 各失败点打原因
    s = rep(s, 'head_null',
        "        const head: Uint8Array | null = await chan.readExactly(12, 60000);\n"
        "        if (head === null) {\n          return false;\n        }",
        "        const head: Uint8Array | null = await chan.readExactly(12, 60000);\n"
        "        if (head === null) {\n"
        "          if (onLog) {\n"
        "            onLog(`v5 \"${item.name}\"：等数据帧头失败（已收 ${subTotal}/${item.length} B，60s 超时或对端断开）`);\n"
        "          }\n          return false;\n        }")

    s = rep(s, 'chunk_null',
        "        const chunk: Uint8Array | null = await chan.readExactly(len, 60000);\n"
        "        if (chunk === null) {\n          return false;\n        }",
        "        const chunk: Uint8Array | null = await chan.readExactly(len, 60000);\n"
        "        if (chunk === null) {\n"
        "          if (onLog) {\n"
        "            onLog(`v5 \"${item.name}\"：数据块 ${len} B 读取失败（已收 ${subTotal}/${item.length}，超时或对端断开）`);\n"
        "          }\n          return false;\n        }")

    s = rep(s, 'mismatch',
        "    if (subTotal !== item.length) {\n"
        "      Log.w(TAG, `v5 接收字节数不符: ${subTotal} != ${item.length}（${path}）`);\n      return false;\n    }",
        "    if (subTotal !== item.length) {\n"
        "      Log.w(TAG, `v5 接收字节数不符: ${subTotal} != ${item.length}（${path}）`);\n"
        "      if (onLog) {\n"
        "        onLog(`v5 \"${item.name}\" 字节数不符：收到 ${subTotal} / 应收 ${item.length}`);\n"
        "      }\n      return false;\n    }")

    # 7) receive 里调用 recvBody 时把 onLog 传下去
    s = rep(s, 'recvbody_call',
        "        const ok: boolean = await V5Transfer.recvBody(chan, item, encData, storage,\n"
        "          (got: number, size: number) => {",
        "        const ok: boolean = await V5Transfer.recvBody(chan, item, encData, storage,\n"
        "          (got: number, size: number) => {")

    # recvBody 调用尾部补 onLog（锚定 onChunk 回调结束 + `});`）
    s = rep(s, 'recvbody_call_tail',
        "              got, size, percent, false, true, '');\n"
        "          });\n        // 收完（无论成败）都要回一个字节：发送端在等它，不回会挂到超时",
        "              got, size, percent, false, true, '');\n"
        "          }, onLog);\n"
        "        // 收完（无论成败）都要回一个字节：发送端在等它，不回会挂到超时")

    # 8) 失败上报处补原因转发（recvBody 内部已打具体原因）
    s = rep(s, 'fail_report',
        "        if (!ok) {\n"
        "          V5Transfer.report(onReport, 'recv', from.devName, item.name, i + 1, items.length,\n"
        "            0, item.length, 0, true, false, `接收失败：${item.name}`);\n"
        "          return false;\n        }",
        "        if (!ok) {\n"
        "          V5Transfer.report(onReport, 'recv', from.devName, item.name, i + 1, items.length,\n"
        "            0, item.length, 0, true, false, `接收失败：${item.name}`);\n"
        "          if (onLog) {\n"
        "            onLog(`v5 第 ${i + 1}/${items.length} 项 \"${item.name}\" 接收失败，本连接结束`);\n"
        "          }\n          return false;\n        }")

    # 9) 收满等待结束帧的提示
    s = rep(s, 'wait_end',
        "      if (subTotal === item.length) {\n"
        "        const tail: Uint8Array | null = await chan.readExactly(12, END_FRAME_WAIT_MS);",
        "      if (subTotal === item.length) {\n"
        "        if (onLog) {\n"
        "          onLog(`v5 \"${item.name}\" 已收满 ${subTotal} B，等待结束帧…`);\n"
        "        }\n"
        "        const tail: Uint8Array | null = await chan.readExactly(12, END_FRAME_WAIT_MS);")

    return s


def patch_lanservice(s):
    old = ("    await V5Transfer.receive(channel, peer, count, encData !== 0, this.storage,\n"
           "      (r: TransferReport) => this.onTransferReport(r));")
    new = ("    await V5Transfer.receive(channel, peer, count, encData !== 0, this.storage,\n"
           "      (r: TransferReport) => this.onTransferReport(r),\n"
           "      // 5.0.47：接收链关键事件接到 UI 日志 —— hilog 抓不到时（无线调试 Unauthorized）\n"
           "      // 也能靠这行定位「多项发送卡死」卡在哪一步\n"
           "      (s: string) => this.pushLog(s));")
    return rep(s, 'ls_call', old, new, 'LanService')


def patch_index(s):
    # B1. busy 清零后补一次 flush
    s = rep(s, 'busy_then',
        "    this.autoSaveBusy = true;\n"
        "    this.autoSaveAlbumBatch(paths, owners, ready).then(() => {\n"
        "      this.autoSaveBusy = false;\n"
        "    });",
        "    this.autoSaveBusy = true;\n"
        "    this.autoSaveAlbumBatch(paths, owners, ready).then(() => {\n"
        "      this.autoSaveBusy = false;\n"
        "      // 5.0.47：batch 的 finally 里那次 flushAutoSave 发生在 busy 清零**之前**\n"
        "      // （被 busy 挡掉），必须在这里补一次，否则弹框期间入队的后续图片\n"
        "      // 永远没人再触发 -> 只有第一次有弹窗（真机复现）。\n"
        "      this.flushAutoSave();\n"
        "    });")

    # B3. 取消分支设 cancelled 标记 + 声明
    s = rep(s, 'cancel_branch',
        "      const uris: string[] = await helper.showAssetsCreationDialog(srcUris, cfgs);\n"
        "      if (uris.length === 0) {\n"
        "        // 用户在确认框上点了取消 —— 系统返回空数组，不是错误\n"
        "        this.toast('已跳过存入相册');\n"
        "        return;\n"
        "      }",
        "      const uris: string[] = await helper.showAssetsCreationDialog(srcUris, cfgs);\n"
        "      if (uris.length === 0) {\n"
        "        // 用户在确认框上点了取消 —— 系统返回空数组，不是错误\n"
        "        this.toast('已跳过存入相册');\n"
        "        cancelled = true;\n"
        "        return;\n"
        "      }")

    # B2. per-file try/catch
    s = rep(s, 'batch_loop',
        "      let ok: number = 0;\n"
        "      for (let i: number = 0; i < n; i++) {\n"
        "        const msg: string = ExportService.copyTo(paths[i], uris[i], Index.baseName(paths[i]));\n"
        "        if (msg.startsWith('已保存')) {\n"
        "          ok += 1;\n"
        "          // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反\n"
        "          const thumb: string = await this.cacheThumb(ctx, paths[i], owners[i]);\n"
        "          const rot: number = this.service.rotOf(thumb) ?? 0;\n"
        "          await this.service.setAlbumIndex(owners[i], uris[i], thumb, rot);\n"
        "          const derr: string | null =\n"
        "            ExportService.deleteFile(this.service.receiveRoot, paths[i]);\n"
        "          if (derr !== null) {\n"
        "            Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${paths[i]}`);\n"
        "          }\n"
        "        }\n"
        "      }",
        "      let ok: number = 0;\n"
        "      for (let i: number = 0; i < n; i++) {\n"
        "        // 5.0.47：单文件失败（copyTo/cacheThumb 抛异常）不再中断整批 ——\n"
        "        //   之前一张图抛异常，后面的图片全部不处理、也不删沙箱副本。\n"
        "        try {\n"
        "          const msg: string = ExportService.copyTo(paths[i], uris[i], Index.baseName(paths[i]));\n"
        "          if (msg.startsWith('已保存')) {\n"
        "            ok += 1;\n"
        "            // ① 出缩略图 ② 记相册 URI ③ 才删沙箱副本 —— 顺序不能反\n"
        "            const thumb: string = await this.cacheThumb(ctx, paths[i], owners[i]);\n"
        "            const rot: number = this.service.rotOf(thumb) ?? 0;\n"
        "            await this.service.setAlbumIndex(owners[i], uris[i], thumb, rot);\n"
        "            const derr: string | null =\n"
        "              ExportService.deleteFile(this.service.receiveRoot, paths[i]);\n"
        "            if (derr !== null) {\n"
        "              Log.w(TAG, `存相册后删沙箱副本失败: ${derr} ${paths[i]}`);\n"
        "            }\n"
        "          }\n"
        "        } catch (x) {\n"
        "          const xe: BusinessError = x as BusinessError;\n"
        "          Log.w(TAG, `单文件存相册失败: ${paths[i]} ${xe.code} ${xe.message}`);\n"
        "        }\n"
        "      }")

    # cancelled / failed 声明（挂在 try 之前 —— 锚定 helper 声明前那两行）
    s = rep(s, 'flags_decl',
        "      const srcUris: string[] = [];\n      const cfgs: photoAccessHelper.PhotoCreationConfig[] = [];",
        "      // 5.0.47：用户取消（cancelled）= 结案不再弹；异常（failed）= 留队重试\n"
        "      let cancelled: boolean = false;\n"
        "      const srcUris: string[] = [];\n      const cfgs: photoAccessHelper.PhotoCreationConfig[] = [];")

    # catch 里标 failed
    s = rep(s, 'catch_failed',
        "    } catch (e) {\n"
        "      const err: BusinessError = e as BusinessError;\n"
        "      Log.w(TAG, `自动存相册失败: ${err.code} ${err.message}`);\n"
        "    } finally {",
        "    } catch (e) {\n"
        "      const err: BusinessError = e as BusinessError;\n"
        "      Log.w(TAG, `自动存相册失败: ${err.code} ${err.message}`);\n"
        "      failed = true;\n"
        "    } finally {")
    # failed 声明（与 cancelled 同处）
    s = rep(s, 'flags_decl2',
        "      // 5.0.47：用户取消（cancelled）= 结案不再弹；异常（failed）= 留队重试\n"
        "      let cancelled: boolean = false;",
        "      // 5.0.47：用户取消（cancelled）= 结案不再弹；异常（failed）= 留队重试\n"
        "      let cancelled: boolean = false;\n"
        "      let failed: boolean = false;")

    # finally：只有「存完/取消」才结案；异常留队重试
    s = rep(s, 'finally_mark',
        "    } finally {\n"
        "      // 弹过框就结案：存了 / 取消了 / 失败了，都不再弹第二次\n"
        "      for (let i: number = 0; i < ready.length; i++) {\n"
        "        this.autoSaveHandled.add(ready[i]);\n"
        "      }",
        "    } finally {\n"
        "      // 5.0.47：存完 / 用户取消 -> 结案；**异常** -> 留队，等下一次 refreshReceived\n"
        "      // 重试（flushAutoSave 只由消息/刷新触发，不会自旋）。之前一律结案，\n"
        "      // 一次系统瞬时错误就永久不弹了。\n"
        "      if (!failed) {\n"
        "        for (let i: number = 0; i < ready.length; i++) {\n"
        "          this.autoSaveHandled.add(ready[i]);\n"
        "        }\n"
        "      }")

    return s


def main():
    if SENTINEL in load(VT):
        print('ALREADY APPLIED')
        return

    vt = patch_v5transfer(load(VT))
    save(VT, vt)

    ls = patch_lanservice(load(LS))
    save(LS, ls)

    idx = patch_index(load(PAGE))
    save(PAGE, idx)

    a = load(APP)
    oldv = '"versionCode": 5000046,\n    "versionName": "5.0.46",'
    newv = '"versionCode": 5000047,\n    "versionName": "5.0.47",'
    assert a.count(oldv) == 1, f'app.json5 {a.count(oldv)}'
    save(APP, a.replace(oldv, newv))

    print('OK: 5.0.47 已应用（接收链 UI 诊断 + 自动存相册三处修复 + 版本号）')


if __name__ == '__main__':
    main()
