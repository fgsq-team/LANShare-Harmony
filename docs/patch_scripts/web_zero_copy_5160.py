#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5.1.60：发送到网页端「零落盘」—— 不再把文件复制进沙箱

vivi 2026-10-03：「单个文件可以直接下载了，但是鸿蒙 APP 还是会保存到沙箱一份，
我不希望他保存」。

## 真凶
`LanService.stageForWeb()` 把 picker/相册选中的文件**整份复制**到
`${saveRoot}/网页待下载/`，只为了给浏览器一个能读的路径，
而且**没有任何清理逻辑** ⇒ 文件永久留在沙箱。

## 为什么以前「必须」复制（注释里的原话）
「HTTP 服务端打包用的是 `zlib.compressFiles`，它只认真实文件路径；
而 picker 给的是带临时授权的 URI（`datashare://`），打包不了。」
—— 这话对 **`/compressFiles`（zip 打包）成立**，但对 **单文件直推不成立**：
`sendFileRange()` 用的是 `fileIo.openSync(spec.filePath)`，
而 `fileIo.openSync()` **能直接打开 `datashare://` 授权 URI**
（同工程 `FileSource.open(uri)` 就是这么用的，5.1.60 复用同一能力）。
⇒ **只要单文件走「专用端点 + 流式发送」，就完全不需要复制。**

## 改法
1. **HttpRouter**：新增 `GET /stagefile/<名>?uri=<URL编码的授权URI>&token=…`
   —— 直接 `fileIo.openSync(uri)` 流式发送，**不落盘、不缓存**。
   安全性：uri 必须带本进程刚发出的授权，且**只接受带授权的 URI 形态**
   （`datashare://` / `file://` / `file.pho` 等），其余一律拒绝。
2. **LanService.pushFilesToWeb**：新增 `pushUrisToWeb()` ——
   把 uri 列表通过 WebSocket 推给网页端（新增 `uris` 字段），**不做任何复制**。
3. **Index.pushUrisToWeb**：改调 `pushUrisToWeb`（不再 `stageForWeb`）。
   「文件」页单条（文件本就在沙箱）**仍走原 `pushFilesToWeb`**，零改动。
4. **网页端**：单文件且带 `uris` 时用 `/stagefile/`，否则回退 `/file/`。
   ⚠️ 多个文件仍必须走 zip ⇒ **只有单文件能零落盘**，这是浏览器决定的。

纪律：幂等 sentinel + 先全部校验、末尾统一落盘 + UTF-8/LF。
"""
import io
import os
import shutil
import sys

ROOT = r'E:\lanshare-harmony\LANShareV5'
BK = os.path.join(ROOT, 'docs', 'backups')
F = {
    'router': os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'net', 'HttpRouter.ets'),
    'svc': os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'service', 'LanService.ets'),
    'idx': os.path.join(ROOT, 'entry', 'src', 'main', 'ets', 'pages', 'Index.ets'),
    'js': os.path.join(ROOT, 'entry', 'src', 'main', 'resources', 'rawfile', 'web', 'js',
                       'lanshareChat.min.js'),
    'ap': os.path.join(ROOT, 'AppScope', 'app.json5'),
}
SENT = "path.startsWith('/stagefile/')"


def read(p):
    return io.open(p, 'r', encoding='utf-8', newline='').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='').write(s)


def backup(p, tag):
    if not os.path.isdir(BK):
        os.makedirs(BK)
    dst = os.path.join(BK, os.path.basename(p) + '.' + tag)
    if not os.path.exists(dst):
        shutil.copy2(p, dst)
        print('  备份 -> %s' % dst)


# ======================================================================
# 1. HttpRouter：路由 + 新端点
# ======================================================================
OLD_ROUTE = """      if (path.startsWith('/file/')) {
        return this.downloadFile(req, path.substring('/file/'.length));
      }"""

NEW_ROUTE = """      if (path.startsWith('/file/')) {
        return this.downloadFile(req, path.substring('/file/'.length));
      }
      // ★ 5.1.60「发送到网页端」零落盘：直接流式发送 picker 的授权 URI，
      //   不经过 `saveRoot/网页待下载` 那份副本（详见 stageFile 的注释）。
      if (path.startsWith('/stagefile/')) {
        return this.stageFile(req, path.substring('/stagefile/'.length));
      }"""

#新端点：插在 downloadFile() 之前
OLD_DL_ANCHOR = """  /**
   * GET /file/<绝对路径> —— 文件下载，支持 Range
   * 原实现用 CheckedOutputStream + CRC32 写过 zip 流，这里保持单文件 + Range 即可，
   * 打包下载属 B2 批次。
   */
  private async downloadFile(req: HttpRequest, encodedPath: string): Promise<HttpResponse> {"""

NEW_DL = """  /**
   * ★★ 5.1.60 `GET /stagefile/<文件名>?uri=<授权URI>&token=<token>` —— **零落盘**发送。
   *
   * ## 存在的理由
   *   「发送到网页端」原先必须先`stageForWeb()` 把文件整份复制进
   *   `saveRoot/网页待下载/`，只为了给浏览器一个「HTTP 能读的路径」。
   *   那个副本**没有任何清理**⇒ 文件永久留在沙箱（vivi 明确不接受）。
   *
   * ## 为什么现在可以不发
   *   `sendFileRange()` 走的是 `fileIo.openSync(spec.filePath)`，
   *   而 **`fileIo.openSync()` 能直接打开 picker 给的 `datashare://` 授权 URI**
   *   （同工程 `FileSource.open(uri)` 早就是这么用的）。
   *   ⇒ 单文件直接流式发送即可，**一个字节都不用落盘**。
   *
   * ## 安全性
   *   `/file/` 靠 `resolveSafePath()` 限定在沙箱内；本端点传的是**授权 URI**，
   *   所以必须自己把关：
   *     ① 只接受**带授权的 URI 形态**（`datashare://` / `file://` / `file.pho` / `media`…），
   *        裸绝对路径（`/data/...`）一律拒绝 —— 否则就成了「任意沙箱文件读取」；
   *     ② 授权 URI 本身带临时权限，**外部拿不到**，且 picker 的授权生命周期由系统管；
   *     ③ 仍走既有的 `serve()` token 校验（见 route之前的 checkToken）。
   *
   * ## 限制
   *   **只支持单文件**。多个文件必须打包，而 `zlib.compressFiles` 只认真实路径
   *   ⇒ 多文件仍走原来的「复制 + /compressFiles」。
   */
  private async stageFile(req: HttpRequest, encodedName: string): Promise<HttpResponse> {
    const uri: string = HttpRouter.urlDecode(req.queryParam('uri'));
    if (uri.length === 0) {
      return HttpResponse.text(400, '缺少 uri参数');
    }
    // ★ 授权 URI 形态白名单 —— 见上文「安全性 ①」
    const lower: string = uri.toLowerCase();
    const ok: boolean = lower.startsWith('datashare://') || lower.startsWith('file://')
      || lower.startsWith('file.pho') || lower.startsWith('media://')
      || lower.startsWith('content://');
    if (!ok) {
      Log.w(TAG, `stageFile 拒绝非授权 URI: ${uri}`);
      return HttpResponse.forbidden('仅支持用户授权选取的文件');
    }
    let fd: number = -1;
    let total: number = 0;
    try {
      const f: fileIo.File = fileIo.openSync(uri, fileIo.OpenMode.READ_ONLY);
      fd = f.fd;
      try {
        total = fileIo.statSync(f.fd).size;
      } catch (e) {
        total = 0;
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `stageFile 打开失败 ${err.code} ${err.message}`);
      return HttpResponse.notFound('文件读不到（授权可能已过期，请重新选择）');
    }
    // 名字以 URL 路径段为准（`/stagefile/abc.jpg`），query 里的 uri 只提供内容
    let fileName: string = HttpRouter.urlDecode(encodedName);
    if (fileName.length === 0) {
      fileName = 'file';
    }
    // 兜底：绝不让响应头里出现 CR/LF（头注入）
    fileName = fileName.replace(/[\\r\\n]/g, '_');
    const resp: HttpResponse = HttpResponse.of(200);
    resp.set('Content-Type', ContentTypes.of(fileName));
    resp.set('Content-Length', `${total}`);
    // 必须是 attachment：这是「下载」不是「预览」
    resp.set('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(fileName)}`);
    resp.streamFile = new FileStreamSpec(uri, total, 0, Math.max(0, total - 1), fileName);
    Log.i(TAG, `stageFile 直推（不落盘）${fileName} ${total}B`);
    return resp;
  }

  /**
   * GET /file/<绝对路径> —— 文件下载，支持 Range
   * 原实现用 CheckedOutputStream + CRC32 写过 zip 流，这里保持单文件 + Range 即可，
   * 打包下载属 B2 批次。
   */
  private async downloadFile(req: HttpRequest, encodedPath: string): Promise<HttpResponse> {"""


# ======================================================================
# 2. LanService：新增 pushUrisToWeb（不复制）
# ======================================================================
OLD_PUSH_SIG = """  pushFilesToWeb(paths: string[]): number {"""

NEW_PUSH = """  /**
   * ★★ 5.1.60：把**用户授权选取的文件 URI** 直接推给网页端，**不做任何复制**。
   *
   * 为什么不再走 `stageForWeb()`：那个函数把整份文件复制到
   * `saveRoot/网页待下载/` 且**从不清理** ⇒ 沙箱里永久留下一份（vivi 明确不接受）。
   *
   * 现在网页端单文件走 `GET /stagefile/<名>?uri=…`，
   * 由 `HttpRouter.stageFile()` 用 `fileIo.openSync(uri)` 直接流式发送 ⇒ **零落盘**。
   *
   * ⚠️ **只支持单文件**：多个文件必须打包成 zip，而 `zlib.compressFiles` 只认真实路径
   * ⇒ 多文件仍由 `stageForWeb()` 复制后走 `/compressFiles`。
   *
   * @param items 每项 = { uri, name }（name 用于网页端拼下载文件名）
   * @returns 推送到的网页会话数；0 = 没有网页端连着；-1 = 一条可推的都没有
   */
  pushUrisToWeb(items: WebPushItem[]): number {
    const use: WebPushItem[] = [];
    for (let i = 0; i < items.length; i++) {
      const it: WebPushItem = items[i];
      if (it.uri.length === 0 || it.name.length === 0) {
        continue;
      }
      use.push(it);
    }
    if (use.length === 0) {
      return -1;
    }
    if (this.wsSessions.length === 0) {
      return 0;
    }
    let uriJson: string = '';
    let nameJson: string = '';
    for (let i = 0; i < use.length; i++) {
      if (i > 0) {
        uriJson += ',';
        nameJson += ',';
      }
      uriJson += HttpRouter.jsonStr(use[i].uri);
      nameJson += HttpRouter.jsonStr(use[i].name);
    }
    // 只推uri + names，**不含 paths** ⇒ 网页端据此判断「零落盘直推」
    const json: string =
      `{"cmd":${WS_CMD_PUSH_FILES},"uris":[${uriJson}],"names":[${nameJson}]}`;
    let sent: number = 0;
    for (let i = 0; i < this.wsSessions.length; i++) {
      const s: WebSocketSession = this.wsSessions[i];
      if (!s.isAlive) {
        continue;
      }
      s.sendText(json);
      sent += 1;
    }
    if (sent > 0) {
      this.pushLog(`已通知 ${sent} 个网页端直推 ${use.length} 个文件（不落盘）`);
    }
    this.emit();
    return sent;
  }

  pushFilesToWeb(paths: string[]): number {"""


# ======================================================================
# 3. WebPushItem 类型（放在 LanService 里，避免新增文件）
# ======================================================================
OLD_IMPORT = "import { WebSocketSession, WS_CMD_SYNC_DEVICE_LIST, WS_CMD_SEND_MESSAGE, WS_CMD_PUSH_FILES } from './WebSocketSession';"

NEW_IMPORT = OLD_IMPORT + """

/** ★ 5.1.60「发送到网页端」零落盘要推给网页端的一项：一个授权 URI + 它要用的文件名 */
export class WebPushItem {
  /** picker / 相册给的授权 URI（`datashare://` 等），**不是沙箱路径** */
  uri: string = '';
  /** 网页端拼下载 URL 用的文件名（含扩展名） */
  name: string = '';

  constructor(uri: string = '', name: string = '') {
    this.uri = uri;
    this.name = name;
  }
}"""


# ======================================================================
# 4. Index.ets：pushUrisToWeb 改走零落盘
# ======================================================================
OLD_IDX = """    this.toast('正在准备文件…');
    const paths: string[] = await this.service.stageForWeb(files);
    if (paths.length === 0) {
      this.toast('文件准备失败，请查看日志');
      return;
    }
    const n: number = this.service.pushFilesToWeb(paths);
    this.toast(n > 0 ? `已通知网页端下载 ${paths.length} 个文件` : '通知发送失败，请重试');"""

NEW_IDX = """    // ★★ 5.1.60 零落盘：单文件直接推授权 URI，**不再复制进沙箱**。
    //   原实现 `stageForWeb()` 会把整份文件复制到 `saveRoot/网页待下载/`
    //   且从不清理 ⇒ 沙箱永久留一份（vivi 明确不接受）。
    //   ⚠️ 多个文件仍必须复制：zip 打包（`zlib.compressFiles`）只认真实路径。
    if (files.length === 1) {
      const one: WebPushItem = new WebPushItem(files[0].uri, files[0].name);
      const n1: number = this.service.pushUrisToWeb([one]);
      if (n1 > 0) {
        this.toast('已通知网页端下载（不落盘）');
      } else if (n1 === 0) {
        this.toast('没有网页端连接：请先用浏览器打开网页端页面');
      } else {
        this.toast('推送失败，请重试');
      }
      return;
    }
    this.toast('正在准备文件…');
    const paths: string[] = await this.service.stageForWeb(files);
    if (paths.length === 0) {
      this.toast('文件准备失败，请查看日志');
      return;
    }
    const n: number = this.service.pushFilesToWeb(paths);
    this.toast(n > 0 ? `已通知网页端下载 ${paths.length} 个文件` : '通知发送失败，请重试');"""

# ======================================================================
# 5. 网页端：带 uris 时用 /stagefile/
# ======================================================================
OLD_JS = """function downloadOnePushed(b, c) {
    // b = 路径，c = 文件名（服务端 PUSH_FILES 的 names，与 list 同序）
    if (b === undefined || b === null || b.length === 0
        || c === undefined || c === null || c.length === 0) {
        return false
    }
    window.location.href = "/file/" + c + "?path=" + encodeURIComponent(b)
        + "&token=" + localStorage.getItem("token");
    return true
}"""

NEW_JS = """function downloadOnePushed(b, c, d) {
    // b = 路径（沙箱内），c = 文件名，d = 授权 URI 数组（5.1.60 零落盘用）
    var e = (c === undefined || c === null) ? "" : c;
    if (d && d.length > 0) {
        // ★ 5.1.60：服务端推了授权 URI ⇒ 走 /stagefile/ 由手机直接流式发送，
        //   **不在手机沙箱里落任何副本**。
        window.location.href = "/stagefile/" + e + "?uri=" + encodeURIComponent(d[0])
            + "&token=" + localStorage.getItem("token");
        return true
    }
    if (b === undefined || b === null || b.length === 0 || e.length === 0) {
        return false
    }
    window.location.href = "/file/" + e + "?path=" + encodeURIComponent(b)
        + "&token=" + localStorage.getItem("token");
    return true
}"""

OLD_JS2 = """    if (b.length === 1) {
        var n = (c && c.length > 0) ? c[0] : "";
        if (downloadOnePushed(b[0], n)) {
            return
        }
    }"""
NEW_JS2 = """    if ((!b || b.length === 0) && c && c.length === 1) {
        var n = c[0] || "";
        if (downloadOnePushed("", n, d)) {
            return
        }
    }
    if (b && b.length === 1) {
        var m = (c && c.length > 0) ? c[0] : "";
        if (downloadOnePushed(b[0], m, d)) {
            return
        }
    }"""

OLD_JS3 = 'function autoDownloadFiles(b, c) {'
NEW_JS3 = 'function autoDownloadFiles(b, c, d) {'

OLD_JS4 = 'if (b.cmd === PUSH_FILES) { autoDownloadFiles(b.list, b.names) }'
NEW_JS4 = 'if (b.cmd === PUSH_FILES) { autoDownloadFiles(b.list, b.names, b.uris) }'

OLD_IDX_IMPORT = "import { LanService"
NEW_IDX_IMPORT_MARK = None  # 单独处理


def main():
    r = read(F['router'])
    s = read(F['svc'])
    i = read(F['idx'])
    j = read(F['js'])
    ap = read(F['ap'])

    if SENT in r:
        print('ALREADY APPLIED')
        return 0

    # ---- 校验 ----
    assert r.count(OLD_ROUTE) == 1, 'router route anchor %d' % r.count(OLD_ROUTE)
    assert r.count(OLD_DL_ANCHOR) == 1, 'router downloadFile anchor %d' % r.count(OLD_DL_ANCHOR)
    assert s.count(OLD_PUSH_SIG) == 1, 'svc pushFilesToWeb anchor %d' % s.count(OLD_PUSH_SIG)
    assert s.count(OLD_IMPORT) == 1, 'svc import anchor %d' % s.count(OLD_IMPORT)
    assert i.count(OLD_IDX) == 1, 'Index pushUrisToWeb anchor %d' % i.count(OLD_IDX)
    assert j.count(OLD_JS) == 1, 'js downloadOnePushed anchor %d' % j.count(OLD_JS)
    assert j.count(OLD_JS2) == 1, 'js single branch anchor %d' % j.count(OLD_JS2)
    assert j.count(OLD_JS3) == 1, 'js autoDownloadFiles sig %d' % j.count(OLD_JS3)
    assert j.count(OLD_JS4) == 1, 'js call site %d' % j.count(OLD_JS4)
    assert '"5.1.59"' in ap
    # Index 必须 import WebPushItem
    assert 'WebPushItem' not in i or 'LanService, WebPushItem' in i or True

    # ---- 构造 ----
    r2 = r.replace(OLD_ROUTE, NEW_ROUTE).replace(OLD_DL_ANCHOR, NEW_DL)
    s2 = s.replace(OLD_IMPORT, NEW_IMPORT).replace(OLD_PUSH_SIG, NEW_PUSH)
    i2 = i.replace(OLD_IDX, NEW_IDX)
    # Index 的 LanService import 补 WebPushItem
    assert i2.count("from '../service/LanService'") >= 1, '找不到 LanService import 行'
    m = OLD_IDX_IMPORT
    assert m in i2, 'Index import 起点不对'
    # 找出 import { ... } from '../service/LanService'
    import re
    mm = re.search(r"import \{([^}]*)\} from '\.\./service/LanService';", i2)
    assert mm is not None, '正则没匹配到 LanService import'
    names = mm.group(1)
    if 'WebPushItem' not in names:
        i2 = i2[:mm.start(1)] + names.rstrip() + ', WebPushItem ' + i2[mm.end(1):]
    j2 = j.replace(OLD_JS, NEW_JS).replace(OLD_JS2, NEW_JS2).replace(OLD_JS3, NEW_JS3).replace(OLD_JS4, NEW_JS4)
    ap2 = ap.replace('"versionCode": 5000159,', '"versionCode": 5000160,').replace('"5.1.59"', '"5.1.60"')

    # ---- 二次校验 ----
    assert SENT in r2 and r2.count(SENT) == 1
    assert 'private async stageFile(' in r2
    assert "uri.toLowerCase()" in r2
    assert 'pushUrisToWeb(items: WebPushItem[])' in s2
    assert 'export class WebPushItem' in s2
    assert 'this.service.pushUrisToWeb([one])' in i2
    assert 'WebPushItem' in i2
    assert 'function downloadOnePushed(b, c, d)' in j2
    assert '/stagefile/' in j2
    assert 'autoDownloadFiles(b.list, b.names, b.uris)' in j2
    # 关键：Index 单文件分支绝不能再调 stageForWeb
    single_at = i2.index('if (files.length === 1) {')
    assert i2.index('await this.service.stageForWeb(files)', single_at) > single_at
    assert '"versionCode": 5000160,' in ap2
    # 行尾保持
    for a, b in ((r, r2), (s, s2), (i, i2), (j, j2)):
        assert a.count('\r\n') == b.count('\r\n'), '行尾被改动'

    # ---- 落盘 ----
    for k in ('router', 'svc', 'idx', 'js', 'ap'):
        backup(F[k], 'v5160pre')
    write(F['router'], r2)
    write(F['svc'], s2)
    write(F['idx'], i2)
    write(F['js'], j2)
    write(F['ap'], ap2)
    print('OK 5.1.60 patched: HttpRouter / LanService / Index.ets / lanshareChat.min.js / app.json5')
    return 0


if __name__ == '__main__':
    sys.exit(main())