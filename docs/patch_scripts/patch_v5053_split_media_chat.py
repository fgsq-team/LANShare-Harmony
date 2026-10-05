# -*- coding: utf-8 -*-
"""
5.0.53（vivi 2026-10-02 要求）
① 接收**多个图片/视频**时，**每个媒体一条聊天记录**（拆分）
② 文件（非媒体）仍保持「一次接收多个文件 = 一条记录」
③ 版本号 -> 5.0.53 / 5000053

为什么拆（真机症状根因）：
  对端一次发 N 张图，本端只产生**一条**「N 个文件」消息 ⇒「消息 id」这个
  最粗的标识被当成了「一张图」的标识。相册 uri / 缩略图文件名 / 旋转角全在
  一批里共用 —— 删一张整批失效，点第二张也没有自己的入口。
  拆成 N 条后，每条消息天然对应一张图，5.0.52 那套 `消息id#媒体序号`
  在新数据上退化成 k 恒为 0 的简单情形，全部既有逻辑自动正确。

幂等：哨兵 `appendFileChat`，打过直接 SKIP。
写文件保持 LF。
"""
import io, sys

LS = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\LanService.ets'
IX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
AJ = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'

SENTINEL = 'private appendFileChat('

# ---------------------------------------------------------------- 1. onTransferReport
LS_A_OLD = """    if (r.ok && r.fileName.length > 0) {
      const incoming: boolean = r.direction !== 'send';
      this.appendChat(incoming, r.peer, this.transferPeerIp, r.fileName,
        incoming ? 'device' : 'app', 'file', r.fileNames.join('\\n'));
    }
"""
LS_A_NEW = """    if (r.ok && r.fileName.length > 0) {
      const incoming: boolean = r.direction !== 'send';
      // ★ 5.0.53：走 appendFileChat —— 接收多个图片/视频时**每个一条消息**
      this.appendFileChat(incoming, r.peer, this.transferPeerIp, r.fileName,
        r.fileNames, incoming ? 'device' : 'app');
    }
"""

# ---------------------------------------------------------------- 2. onWebUploadEnd
LS_B_OLD = """      // 与「收到对端文件」一样在消息页留一条记录，点开可跳到文件页
      this.appendChat(true, '网页端', '', label, 'web', 'file');
"""
LS_B_NEW = """      // 与「收到对端文件」一样在消息页留一条记录，点开可跳到文件页
      // ★ 5.0.53：同样按「媒体每个一条」拆 —— 顺便把 names 传下去，
      //   网页端上传的图/视频这才有缩略图（以前只传了合并后的 label，UI 拿不到名字）。
      this.appendFileChat(true, '网页端', '', label, names, 'web');
"""

# ---------------------------------------------------------------- 3. 新增方法
LS_C_OLD = """    this.scheduleChatSave();
  }

  /**
   * 把一条聊天内容推给所有网页会话。
"""
LS_C_NEW = """    this.scheduleChatSave();
  }

  /**
   * ★ 5.0.53（vivi 2026-10-02 要求）：一条文件传输记录 ——
   *   **接收多个图片/视频时，每个媒体一条记录**；其它情况仍合并成一条。
   *
   * ⚠️ 为什么必须拆（这是「删一张，整批失效」的真根因）：
   *   对端一次发 N 张图，本端只产生**一条**「N 个文件」消息
   *   （`V5Transfer` / `FileTransfer` 都是收完整批才回一次终态，名字合并成
   *   「N 个文件」）。于是「消息 id」这个**最粗**的标识被当成了「一张图」的
   *   标识 —— 相册 uri、缩略图文件名、旋转角全在一批里共用：
   *   删掉其中一张 ⇒ 整条记录标废 ⇒ 这一批**全部**提示「已从相册删除」；
   *   点击也只有一个入口（只能指向第 1 张），点不到第 2 张。
   *   拆成 N 条之后，每条消息天然对应一张图 —— 所有既有逻辑
   *   （缩略图 / 跳相册 / 删除 / ForEach key）自动正确，不需要再靠下标兜。
   *
   * ⚠️ **只拆接收方向**（vivi 明确要求）：自己发出去的多张图仍是一条
   *   「已发送 N 个文件」—— 发送侧点气泡只是跳「文件」页，没有相册语义，
   *   拆开只会让聊天记录变啰嗦。
   *
   * ⚠️ **整批全是媒体**才拆。混合批（1 张图 + 1 个 zip）保持一条 ——
   *   否则「图片一条、打包文件又一条」会让用户以为收了两次。
   *
   * @param label 合并后的文案（单发 = 文件名，多发 = 「N 个文件」）
   * @param names 这一批的**全部文件名**（顺序 = 传输顺序），可能为空数组
   */
  private appendFileChat(incoming: boolean, peerName: string, peerIp: string,
                         label: string, names: string[], source: string): void {
    if (incoming && names.length > 1 && LanService.allMedia(names)) {
      for (let i: number = 0; i < names.length; i++) {
        // 每条只带**自己那个**文件名：`content` = 名字（气泡文案）、
        // `files` = 名字（UI 靠它解析出媒体下标 0）。
        this.appendChat(true, peerName, peerIp, names[i], source, 'file', names[i]);
      }
      return;
    }
    this.appendChat(incoming, peerName, peerIp, label, source, 'file', names.join('\\n'));
  }

  /** 这一批是不是**全是**图片/视频 —— 决定要不要拆成「每个一条消息」 */
  private static allMedia(names: string[]): boolean {
    if (names.length === 0) {
      return false;
    }
    for (let i: number = 0; i < names.length; i++) {
      if (!LanService.isMediaFileName(names[i])) {
        return false;
      }
    }
    return true;
  }

  /**
   * 按扩展名判断图片/视频（表与 `Index.ets` 的 `isImageName` / `isVideoName` 完全一致）。
   *
   * ⚠️ 两边必须是**同一个判定**：这里决定「接收时拆不拆消息」，
   *   `Index.ets` 决定「显不显示缩略图 / 点开进不进预览」。
   *   一旦不一致就会出现「拆了却没缩略图」或「没拆却有缩略图」的错位。
   *   所以 `Index.isMediaName` 现在直接委托到本方法（唯一真源）。
   */
  static isMediaFileName(name: string): boolean {
    const dot: number = name.lastIndexOf('.');
    if (dot < 0) {
      return false;
    }
    const ext: string = name.substring(dot + 1).toLowerCase();
    return ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'gif'
      || ext === 'webp' || ext === 'bmp' || ext === 'heic' || ext === 'heif'
      || ext === 'avif' || ext === 'ico' || ext === 'tif' || ext === 'tiff'
      || ext === 'mp4' || ext === 'mov' || ext === 'mkv' || ext === 'webm'
      || ext === 'avi' || ext === '3gp' || ext === 'm4v' || ext === 'ts'
      || ext === 'flv' || ext === 'wmv' || ext === 'rmvb' || ext === 'mpg'
      || ext === 'mpeg' || ext === 'ogv';
  }

  /**
   * 把一条聊天内容推给所有网页会话。
"""

# ---------------------------------------------------------------- 4. Index.isMediaName 委托
IX_A_OLD = """  /** 图片 or 视频 —— 「能在 App 内直接打开」的那一类 */
  private isMediaName(name: string): boolean {
    return this.isImageName(name) || this.isVideoName(name);
  }
"""
IX_A_NEW = """  /**
   * 图片 or 视频 —— 「能在 App 内直接打开」的那一类。
   *
   * ★ 5.0.53：改为**委托** `LanService.isMediaFileName`（唯一真源）——
   *   它决定「接收时拆不拆成每张一条消息」，这里决定「显不显示缩略图」，
   *   两边一旦不一致就会出现「拆了却没缩略图」或「没拆却有缩略图」的错位。
   */
  private isMediaName(name: string): boolean {
    return LanService.isMediaFileName(name);
  }
"""

# ---------------------------------------------------------------- 5. 版本号
AJ_OLD = """    "versionCode": 5000052,
    "versionName": "5.0.52",
"""
AJ_NEW = """    "versionCode": 5000053,
    "versionName": "5.0.53",
"""


def apply(path, pairs, label):
    s = io.open(path, encoding='utf-8', newline='').read()
    for i, (old, new) in enumerate(pairs):
        assert s.count(old) == 1, '%s 锚点#%d 命中 %d 次' % (label, i + 1, s.count(old))
        assert s.count(new) == 0, '%s 新文本#%d 此前已存在' % (label, i + 1)
    for old, new in pairs:
        s = s.replace(old, new)
    return s


ls_src = io.open(LS, encoding='utf-8', newline='').read()
if SENTINEL in ls_src:
    print('ALREADY APPLIED')
    sys.exit(0)

new_ls = apply(LS, [(LS_A_OLD, LS_A_NEW), (LS_B_OLD, LS_B_NEW), (LS_C_OLD, LS_C_NEW)], 'LanService')
new_ix = apply(IX, [(IX_A_OLD, IX_A_NEW)], 'Index')
new_aj = apply(AJ, [(AJ_OLD, AJ_NEW)], 'app.json5')

# 三道保险：关键字残留 / 括号增量 / 新符号齐备
assert 'this.appendChat(incoming, r.peer' not in new_ls, 'LS: onTransferReport 旧调用仍在'
assert "this.appendChat(true, '网页端', '', label, 'web', 'file');" not in new_ls, 'LS: 网页上传旧调用仍在'
assert new_ls.count('this.appendFileChat(') == 2, 'LS: appendFileChat 调用数应为 2，实为 %d' % new_ls.count('this.appendFileChat(')
assert new_ls.count('private appendFileChat(') == 1
assert new_ls.count('static isMediaFileName(') == 1
assert new_ls.count('private static allMedia(') == 1
assert 'LanService.isMediaFileName(name)' in new_ix, 'IX: 未委托'
assert '5000053' in new_aj and '"5.0.53"' in new_aj

# 括号平衡（只看增量是否一致）
ix_src = io.open(IX, encoding='utf-8', newline='').read()
aj_src = io.open(AJ, encoding='utf-8', newline='').read()
for tag, before, after in [('LanService', ls_src, new_ls),
                           ('Index', ix_src, new_ix),
                           ('app.json5', aj_src, new_aj)]:
    delta = {}
    for ch in '{}()[]':
        delta[ch] = after.count(ch) - before.count(ch)
    print('%s 括号增量: %s' % (tag, delta))

io.open(LS, 'w', encoding='utf-8', newline='\n').write(new_ls)
io.open(IX, 'w', encoding='utf-8', newline='\n').write(new_ix)
io.open(AJ, 'w', encoding='utf-8', newline='\n').write(new_aj)
print('OK: 5.0.53 已应用')
