# -*- coding: utf-8 -*-
"""
5.0.38：收到图片/视频后**自动存进系统相册**（免权限）。

背景（2026-10-01 官方文档取证）：
  * `ohos.permission.WRITE_IMAGEVIDEO` 是受限权限，普通应用申请不到；
  * 但 `photoAccessHelper.showAssetsCreationDialog` **不需要任何权限声明** ——
    弹一次系统确认框，用户同意后返回一批带写权限的媒体 URI，往里写字节就落相册。
  * 工程里 `saveImageToAlbum()` 已经在用它，但入口只有「长按气泡 / 预览顶栏」，
    是手动的。本补丁把它接到「接收完成」那一刻，做成一个可关的开关（默认开）。

改动清单：
  Index.ets
    1. @State autoAlbum（默认 true）
    2. onSnapshot 聊天条数变化分支：捕获 oldCount，新增消息里挑出「刚收到的图片/视频」触发自动保存
       ⚠️ 用 timeMs 60 秒新鲜度挡掉「启动恢复历史聊天」那一茬条数跳变
    3. 新增 autoSaveNewMedia() / autoSaveAlbumBatch()（整批一次弹框）
    4. 设置区新增「收到图片/视频自动存相册」开关 + switchAutoAlbum()
  LanService.ets
    5. autoAlbum 偏好：getter / setAutoAlbum() / loadAutoAlbumPref()，持久化到 PREF_CFG

幂等：每步各用自己的哨兵串判重；先全部校验、最后统一落盘。
"""
import io, sys

IDX = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'
SVC = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/service/LanService.ets'

idx = io.open(IDX, encoding='utf-8', newline='').read()
svc = io.open(SVC, encoding='utf-8', newline='').read()
orig_idx, orig_svc = idx, svc


def rep(s, old, new, tag):
    """精确替换一次；old 必须唯一。"""
    n = s.count(old)
    if n != 1:
        print('ERROR [%s]: old 出现 %d 次（应为 1）' % (tag, n))
        sys.exit(1)
    return s.replace(old, new, 1)


# ---------------------------------------------------------------- 1. @State
if '@State autoAlbum: boolean' in idx:
    print('SKIP 1: @State autoAlbum 已存在')
else:
    old = '  @State showAbout: boolean = false;\n'
    new = (old +
           '  /** 收到图片/视频后自动存进系统相册（持久化在 LanService，默认开） */\n'
           '  @State autoAlbum: boolean = true;\n')
    idx = rep(idx, old, new, 'state')

# ------------------------------------------------- 2. 聊天条数变化分支挂钩
if 'this.autoSaveNewMedia(oldCount);' in idx:
    print('SKIP 2: 自动保存挂钩已存在')
else:
    old = ('    if (s.chat.length !== this.lastChatCount) {\n'
           '      this.lastChatCount = s.chat.length;\n'
           '      this.chat = s.chat.slice();\n'
           '      // 聊天条数变了 -> 重算每条消息的媒体路径（新收到的图/视频要能立刻出缩略图）\n'
           '      this.syncChatMediaPaths();\n')
    new = ('    if (s.chat.length !== this.lastChatCount) {\n'
           '      const oldCount: number = this.lastChatCount;\n'
           '      this.lastChatCount = s.chat.length;\n'
           '      this.chat = s.chat.slice();\n'
           '      // 聊天条数变了 -> 重算每条消息的媒体路径（新收到的图/视频要能立刻出缩略图）\n'
           '      this.syncChatMediaPaths();\n'
           '      // 5.0.38：刚收到的图片/视频 -> 自动存相册（见 autoSaveNewMedia 注释）\n'
           '      this.autoSaveNewMedia(oldCount);\n')
    idx = rep(idx, old, new, 'hook')

# ------------------------------------------------------- 3. 两个新方法
if 'private async autoSaveAlbumBatch' in idx:
    print('SKIP 3: 自动保存方法已存在')
else:
    old = '  /** 把文件名压成系统允许的相册 title（非法字符统一换成下划线） */\n'
    new = (
        '  /**\n'
        '   * 5.0.38：刚收到的图片/视频 -> 自动存进系统相册。\n'
        '   *\n'
        '   * ⚠️ 为什么只认「新增的那几条」：聊天条数变化有两个来源 ——\n'
        '   *   ① 真的收到新文件；② 启动时 `restoreChat` 把历史记录灌进来。\n'
        '   *   后者条数也会跳变，如果不管，每次开 App 都会把历史里所有图视频\n'
        '   *   重新弹一遍保存框。用 `timeMs` 的 60 秒新鲜度把这一茬挡掉。\n'
        '   *\n'
        '   * @param oldCount 本次变化的**前**一条聊天条数（新增消息 = chat[oldCount..]）\n'
        '   */\n'
        '  private autoSaveNewMedia(oldCount: number): void {\n'
        '    if (!this.autoAlbum) {\n'
        '      return;\n'
        '    }\n'
        '    if (oldCount >= this.chat.length) {\n'
        '      return;\n'
        '    }\n'
        '    const now: number = Date.now();\n'
        '    const paths: string[] = [];\n'
        '    for (let i: number = oldCount; i < this.chat.length; i++) {\n'
        '      const m: ChatMessage = this.chat[i];\n'
        '      if (!m.incoming || m.kind !== \'file\') {\n'
        '        continue;\n'
        '      }\n'
        '      if (now - m.timeMs > 60000) {\n'
        '        continue;\n'
        '      }\n'
        '      // 单发走 content 反查出来的那一条；一批文件走 chatMediaGroups\n'
        '      const one: string = this.chatMediaPaths.get(m.id) ?? \'\';\n'
        '      if (one.length > 0 && !paths.includes(one)) {\n'
        '        paths.push(one);\n'
        '      }\n'
        '      const group: string[] | undefined = this.chatMediaGroups.get(m.id);\n'
        '      if (group !== undefined) {\n'
        '        for (let k: number = 0; k < group.length; k++) {\n'
        '          if (!paths.includes(group[k])) {\n'
        '            paths.push(group[k]);\n'
        '          }\n'
        '        }\n'
        '      }\n'
        '    }\n'
        '    if (paths.length === 0) {\n'
        '      return;\n'
        '    }\n'
        '    this.autoSaveAlbumBatch(paths);\n'
        '  }\n'
        '\n'
        '  /**\n'
        '   * 整批存进系统相册 —— **只弹一次**确认框。\n'
        '   *\n'
        '   * `showAssetsCreationDialog` 一次可以传 N 个源文件 + N 份配置，\n'
        '   * 返回 N 个带写权限的媒体 URI，逐个 `ExportService.copyTo` 写字节即可。\n'
        '   * ⚠️ 不需要任何权限声明（WRITE_IMAGEVIDEO 是受限权限，申请不到），\n'
        '   *    前提只有一条：module.json5 的 abilities 里配了 label 和 icon，\n'
        '   *    否则确认框显示不出应用名。\n'
        '   * ⚠️ 拷贝是同步逐块的，先把提示 toast 画出去（yieldOnce 让一帧）再开拷。\n'
        '   */\n'
        '  private async autoSaveAlbumBatch(paths: string[]): Promise<void> {\n'
        '    try {\n'
        '      const ctx: common.UIAbilityContext =\n'
        '        this.getUIContext().getHostContext() as common.UIAbilityContext;\n'
        '      const helper: photoAccessHelper.PhotoAccessHelper =\n'
        '        photoAccessHelper.getPhotoAccessHelper(ctx);\n'
        '      const srcUris: string[] = [];\n'
        '      const cfgs: photoAccessHelper.PhotoCreationConfig[] = [];\n'
        '      for (let i: number = 0; i < paths.length; i++) {\n'
        '        const name: string = Index.baseName(paths[i]);\n'
        '        const dot: number = name.lastIndexOf(\'.\');\n'
        '        const isVideo: boolean = this.isVideoName(name);\n'
        '        const cfg: photoAccessHelper.PhotoCreationConfig = {\n'
        '          title: Index.safeAlbumTitle(dot > 0 ? name.substring(0, dot) : name),\n'
        '          fileNameExtension: dot > 0 ? name.substring(dot + 1).toLowerCase()\n'
        '            : (isVideo ? \'mp4\' : \'jpg\'),\n'
        '          photoType: isVideo ? photoAccessHelper.PhotoType.VIDEO\n'
        '            : photoAccessHelper.PhotoType.IMAGE\n'
        '        };\n'
        '        cfgs.push(cfg);\n'
        '        srcUris.push(this.imageUri(paths[i]));\n'
        '      }\n'
        '      const uris: string[] = await helper.showAssetsCreationDialog(srcUris, cfgs);\n'
        '      if (uris.length === 0) {\n'
        '        // 用户在确认框上点了取消 —— 系统返回空数组，不是错误\n'
        '        this.toast(\'已跳过存入相册\');\n'
        '        return;\n'
        '      }\n'
        '      this.toast(`正在存入相册（${uris.length} 个）…`);\n'
        '      await Index.yieldOnce();\n'
        '      const n: number = uris.length < paths.length ? uris.length : paths.length;\n'
        '      let ok: number = 0;\n'
        '      for (let i: number = 0; i < n; i++) {\n'
        '        const msg: string = ExportService.copyTo(paths[i], uris[i], Index.baseName(paths[i]));\n'
        '        if (msg.startsWith(\'已保存\')) {\n'
        '          ok += 1;\n'
        '        }\n'
        '      }\n'
        '      this.toast(ok > 0 ? `已存入相册 ${ok} 个` : \'存入相册失败\');\n'
        '      Log.i(TAG, `自动存相册：${ok}/${n}`);\n'
        '    } catch (e) {\n'
        '      const err: BusinessError = e as BusinessError;\n'
        '      Log.w(TAG, `自动存相册失败: ${err.code} ${err.message}`);\n'
        '    }\n'
        '  }\n'
        '\n' + old)
    idx = rep(idx, old, new, 'methods')

# --------------------------------------------------- 4a. 设置区开关（UI）
if '收到图片/视频自动存相册' in idx:
    print('SKIP 4a: 开关 UI 已存在')
else:
    old = ('        Toggle({ type: ToggleType.Switch, isOn: this.snapshot.webOpen })\n'
           '          .onChange((on: boolean) => this.switchWebOpen(on))\n'
           '      }\n'
           '      .width(\'100%\')\n'
           '      .alignItems(VerticalAlign.Center)\n')
    new = old + (
        '\n'
        '      // ---------------- 收到图片/视频自动存相册 ----------------\n'
        '      Row({ space: 8 }) {\n'
        '        Column({ space: 2 }) {\n'
        '          Text(\'收到图片/视频自动存相册\')\n'
        '            .fontSize(13)\n'
        '            .fontColor(C_TEXT)\n'
        '          Text(this.autoAlbum\n'
        '            ? \'接收完成后弹一次确认框，同意即存入系统相册\'\n'
        '            : \'只留在应用内，不写入系统相册\')\n'
        '            .fontSize(11)\n'
        '            .fontColor(C_SUB)\n'
        '        }\n'
        '        .alignItems(HorizontalAlign.Start)\n'
        '        .layoutWeight(1)\n'
        '\n'
        '        Toggle({ type: ToggleType.Switch, isOn: this.autoAlbum })\n'
        '          .onChange((on: boolean) => this.switchAutoAlbum(on))\n'
        '      }\n'
        '      .width(\'100%\')\n'
        '      .alignItems(VerticalAlign.Center)\n')
    idx = rep(idx, old, new, 'toggle-ui')

# --------------------------------------------------- 4b. switchAutoAlbum
if 'private async switchAutoAlbum' in idx:
    print('SKIP 4b: switchAutoAlbum 已存在')
else:
    old = ('  /** 切换「网页免确认」（对应原 Config.WEB_OPEN） */\n'
           '  private async switchWebOpen(on: boolean): Promise<void> {\n'
           '    await this.service.setWebOpen(on);\n'
           '  }\n')
    new = old + (
        '\n'
        '  /** 切换「收到图片/视频自动存相册」 */\n'
        '  private async switchAutoAlbum(on: boolean): Promise<void> {\n'
        '    this.autoAlbum = on;\n'
        '    await this.service.setAutoAlbum(on);\n'
        '  }\n')
    idx = rep(idx, old, new, 'switch-method')

# --------------------------------------------------- 4c. 启动时读偏好
if 'this.autoAlbum = this.service.autoAlbumOn;' in idx:
    print('SKIP 4c: 偏好读取已存在')
else:
    old = '    this.loadVersion();\n'
    new = old + '    this.autoAlbum = this.service.autoAlbumOn;\n'
    idx = rep(idx, old, new, 'load-pref')

# --------------------------------------------------- 5a. LanService 开关
if 'async setAutoAlbum(' in svc:
    print('SKIP 5a: LanService setAutoAlbum 已存在')
else:
    old = '  /**\n   * 恢复默认设备名（设备市场名）。\n'
    new = (
        '  /**\n'
        '   * 收到图片/视频后自动存相册。**默认开** —— 用户要的正是「像捷传那样」的体验。\n'
        '   * 走的 `showAssetsCreationDialog` 不需要任何权限声明，弹一次确认框即可。\n'
        '   */\n'
        '  private autoAlbumPref: boolean = true;\n'
        '\n'
        '  get autoAlbumOn(): boolean {\n'
        '    return this.autoAlbumPref;\n'
        '  }\n'
        '\n'
        '  private async loadAutoAlbumPref(ctx: common.UIAbilityContext): Promise<void> {\n'
        '    try {\n'
        '      const store: preferences.Preferences = await preferences.getPreferences(ctx, PREF_CFG);\n'
        '      const saved: Object = await store.get(\'autoAlbum\', true);\n'
        '      if (typeof saved === \'boolean\') {\n'
        '        this.autoAlbumPref = saved;\n'
        '      }\n'
        '    } catch (e) {\n'
        '      Log.w(TAG, \'读取「自动存相册」偏好失败\');\n'
        '    }\n'
        '  }\n'
        '\n'
        '  async setAutoAlbum(on: boolean): Promise<void> {\n'
        '    this.autoAlbumPref = on;\n'
        '    if (this.ctx !== null) {\n'
        '      try {\n'
        '        const store: preferences.Preferences = await preferences.getPreferences(this.ctx, PREF_CFG);\n'
        '        await store.put(\'autoAlbum\', on);\n'
        '        await store.flush();\n'
        '      } catch (e) {\n'
        '        Log.w(TAG, \'保存「自动存相册」开关失败\');\n'
        '      }\n'
        '    }\n'
        '    this.pushLog(on ? \'已开启「收到图片/视频自动存相册」\' : \'已关闭「自动存相册」\');\n'
        '    this.emit();\n'
        '  }\n'
        '\n' + old)
    svc = rep(svc, old, new, 'svc-flag')

# --------------------------------------------------- 5b. 初始化时加载
if 'await this.loadAutoAlbumPref(ctx);' in svc:
    print('SKIP 5b: loadAutoAlbumPref 调用已存在')
else:
    old = ('    // 设备名偏好必须在组装 self.devName 之前就绪（见 startSharing 第 3 步的取用逻辑）\n'
           '    await this.loadDeviceNamePref(ctx);\n')
    new = old + '    await this.loadAutoAlbumPref(ctx);\n'
    svc = rep(svc, old, new, 'svc-load')

# --------------------------------------------------- 落盘
if idx != orig_idx:
    io.open(IDX, 'w', encoding='utf-8', newline='').write(idx)
    print('WROTE Index.ets (+%d 字符)' % (len(idx) - len(orig_idx)))
if svc != orig_svc:
    io.open(SVC, 'w', encoding='utf-8', newline='').write(svc)
    print('WROTE LanService.ets (+%d 字符)' % (len(svc) - len(orig_svc)))
print('DONE')
