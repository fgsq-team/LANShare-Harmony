# -*- coding: utf-8 -*-
"""
5.0.43：修「应用重启后缩略图丢失、点击又跳回文件 tab」。

根因（两处，都指向同一现象）：
  ① ★ 索引持久化**把 key 丢了**。
     `persistAlbumIndex()` 只 push 了 value（形如 `uri|thumb`），**没写消息 id**；
     `loadAlbumIndex()` 读回来时又用 `segs[0]`（= 相册 URI）当 key。
     于是：重启前 albumMap 在内存里、key 是 m.id，一切正常；
           重启后从 preferences 恢复，key 全变成相册 URI → `albumPart(m.id, n)` 永远查不到
           → 缩略图没了 + `onFileBubbleClick` 拿不到相册 URI → 退回「跳文件 tab」。
  ② 缩略图缓存在 `ctx.cacheDir` —— 鸿蒙**会在存储压力下清 cacheDir**（应用重启也可能丢）。
     挪到 `ctx.filesDir`（聊天历史就存在那儿，同一套持久语义）。

附带：`dropAlbumIndex()` 清索引时把对应缩略图文件也删掉，否则挪到 filesDir 后会一直累积。

幂等：靠哨兵串判重。
"""
import io
import sys

IDX = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'
SVC = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/service/LanService.ets'

si = io.open(IDX, encoding='utf-8', newline='').read()
sv = io.open(SVC, encoding='utf-8', newline='').read()

if '5.0.43' in si and 'segs.length >= 3' in sv:
    print('ALREADY APPLIED')
    sys.exit(0)

orig_i, orig_s = si, sv


def rep_i(old, new, tag):
    global si
    c = si.count(old)
    if c != 1:
        print('ERROR [%s]: 锚点出现 %d 次' % (tag, c))
        sys.exit(1)
    si = si.replace(old, new, 1)


def rep_s(old, new, tag):
    global sv
    c = sv.count(old)
    if c != 1:
        print('ERROR [%s]: 锚点出现 %d 次' % (tag, c))
        sys.exit(1)
    sv = sv.replace(old, new, 1)


# ============================================================ 1. LanService：持久化带上 key
OLD_PERSIST = '''      const rows: string[] = [];
      for (const k of this.albumMap.keys()) {
        rows.push(this.albumMap.get(k) ?? '');
      }
      await store.put('albumIndex', rows.join('\\n'));'''
NEW_PERSIST = '''      const rows: string[] = [];
      for (const k of this.albumMap.keys()) {
        const v: string = this.albumMap.get(k) ?? '';
        if (k.length > 0 && v.length > 0) {
          // ⚠️ 5.0.43：行格式必须是 `id|uri|thumb` —— **key（消息 id）必须一起写进去**。
          //    5.0.39~5.0.42 只写了 `uri|thumb`，读回来时拿 uri 当 key，
          //    于是重启后 `albumPart(m.id, n)` 永远查不到 —— 缩略图丢、点击又跳回文件 tab。
          rows.push(`${k}|${v}`);
        }
      }
      await store.put('albumIndex', rows.join('\\n'));'''
rep_s(OLD_PERSIST, NEW_PERSIST, 'persist')

# ============================================================ 2. LanService：按带 key 的格式读回
OLD_LOAD = '''      if (typeof raw === 'string') {
        const rows: string[] = (raw as string).split('\\n');
        for (let i: number = 0; i < rows.length; i++) {
          const segs: string[] = rows[i].split('|');
          if (segs.length >= 2 && segs[0].length > 0) {
            this.albumMap.set(segs[0], rows[i]);
          }
        }
      }'''
NEW_LOAD = '''      if (typeof raw === 'string') {
        const rows: string[] = (raw as string).split('\\n');
        let dropped: number = 0;
        for (let i: number = 0; i < rows.length; i++) {
          const row: string = rows[i];
          if (row.length === 0) {
            continue;
          }
          const segs: string[] = row.split('|');
          if (segs.length >= 3 && segs[0].length > 0) {
            // 5.0.43：行格式 `id|uri|thumb`。存回 map 的 value 仍是 `uri|thumb`
            //         —— UI 的 `albumPart(id, 0/1)` 就是按这两段取的，不用跟着改。
            this.albumMap.set(segs[0], row.substring(segs[0].length + 1));
          } else {
            // 老版本写进去的行只有 `uri|thumb`，**没有 id**，还原不出 key ——
            // 那种行本来也查不到，留着只会让索引越来越脏，直接丢掉。
            dropped = dropped + 1;
          }
        }
        if (dropped > 0) {
          Log.i(TAG, `丢弃 ${dropped} 条缺 id 的旧相册索引（5.0.42 及更早写的）`);
        }
      }'''
rep_s(OLD_LOAD, NEW_LOAD, 'load')

# ============================================================ 3. LanService：删索引时连缩略图一起删
OLD_DROP = '''  private dropAlbumIndex(ids: string[]): void {
    let hit: boolean = false;
    for (let i: number = 0; i < ids.length; i++) {
      if (this.albumMap.delete(ids[i])) {
        hit = true;
      }
    }'''
NEW_DROP = '''  private dropAlbumIndex(ids: string[]): void {
    let hit: boolean = false;
    for (let i: number = 0; i < ids.length; i++) {
      const row: string | undefined = this.albumMap.get(ids[i]);
      if (row === undefined) {
        continue;
      }
      this.albumMap.delete(ids[i]);
      hit = true;
      // 5.0.43：缩略图缓存已挪到 filesDir（不会再被系统自动清），
      //         删记录时必须自己删掉，否则会一直堆着。⚠️ 相册里那一份**不动**。
      const segs: string[] = row.split('|');
      const thumb: string = segs.length >= 2 ? segs[1] : '';
      if (thumb.length > 0) {
        try {
          fileIo.unlinkSync(thumb);
        } catch (x) {
          // 已经不在了就算了
        }
      }
    }'''
rep_s(OLD_DROP, NEW_DROP, 'drop')

# ============================================================ 4. Index：缩略图挪到 filesDir
rep_i('      const dir: string = `${ctx.cacheDir}/album_thumbs`;',
      '      // ⚠️ 5.0.43：从 `cacheDir` 挪到 `filesDir` —— 鸿蒙**会清 cacheDir**（存储压力下，\n'
      '      //    应用重启也可能丢），缩略图一丢就又变回「点气泡跳文件 tab」了。\n'
      '      const dir: string = `${ctx.filesDir}/album_thumbs`;',
      'thumb-dir')

rep_i('   * 把收到的图/视频做成 320px 小图存进 `cacheDir/album_thumbs`，',
      '   * 把收到的图/视频做成 320px 小图存进 `filesDir/album_thumbs`，',
      'doc-dir')

# ============================================================ 5. 头部变更表
OLD_DOC = (' * | 沙箱副本删了缩略图还会在吗 | 会。`cacheThumb()` 在删之前把小图写进 `cacheDir/album_thumbs/<msgid>.jpg`，'
           '并记下真实宽高比；`bubbleMediaPath()` 优先用沙箱那份、没了就用缓存图。⚠️ 为什么不读相册 URI：那是个**写授权** URI，回头去读不一定读得到 |\n')
NEW_DOC = (' * | 沙箱副本删了缩略图还会在吗 | 会。`cacheThumb()` 在删之前把小图写进 `filesDir/album_thumbs/<msgid>.jpg`，'
           '并记下真实宽高比；`bubbleMediaPath()` 优先用沙箱那份、没了就用缓存图。⚠️ 为什么不读相册 URI：那是个**写授权** URI，回头去读不一定读得到 |\n'
           ' * | ★ 重启后缩略图全丢、点击又跳回文件 tab（5.0.43）| **索引持久化把 key 丢了**：落盘时只写了 value（`uri|thumb`）没写消息 id，'
           '读回来却用 `segs[0]`（相册 URI）当 key ⇒ 重启前 key 是 `m.id`（内存里，正常），重启后 key 变成 URI ⇒ `albumPart(m.id,n)` 永远查不到。'
           '修法：行格式改成 `id|uri|thumb`；旧的两段式行还原不出 id，直接丢弃。⚠️ 教训：**Map 持久化必须把 key 一起写进去**，'
           '而"读回来时用第 0 段当 key"这种写法编译期、运行期都不报错，只有重启才现形 |\n'
           ' * | ★ 缩略图为什么从 cacheDir 挪到 filesDir | 鸿蒙**会在存储压力下清 `cacheDir`**（应用重启也可能丢）。'
           '缩略图是"沙箱副本删了之后唯一的一份"，不能放会被自动清的地方。顺带 `dropAlbumIndex()` 删记录时连缩略图文件一起删，否则会一直累积 |\n')
rep_i(OLD_DOC, NEW_DOC, 'header-doc')

if si == orig_i and sv == orig_s:
    print('NO CHANGE')
    sys.exit(1)

io.open(IDX, 'w', encoding='utf-8', newline='').write(si)
io.open(SVC, 'w', encoding='utf-8', newline='').write(sv)
print('PATCH OK')
