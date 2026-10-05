# -*- coding: utf-8 -*-
"""
5.0.43 补丁 B：迁移 5.0.42 及更早留在 `cacheDir` 里的缩略图。

背景：那些版本的索引行只有 `uri|thumb`、**没有消息 id**，升级后按新格式读会被丢弃
      （还原不出 key），那些消息就永远找不到缩略图了。
补救：缩略图的**文件名就是消息 id**（`cacheThumb()` 用的是 `${id}.jpg`），
     所以可以扫旧目录 → 搬到 filesDir → 按文件名重建索引条目。
     ⚠️ 补出来的条目**只有缩略图、没有相册 URI**（旧行的 uri 找不到主人了），
     所以点击不会跳相册，但至少缩略图回来了，不会再退化成「跳文件 tab」。
幂等：靠哨兵串判重。
"""
import io
import sys

SVC = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/service/LanService.ets'
sv = io.open(SVC, encoding='utf-8', newline='').read()

if 'migrateThumbCache' in sv:
    print('ALREADY APPLIED')
    sys.exit(0)

orig = sv


def rep(old, new, tag):
    global sv
    c = sv.count(old)
    if c != 1:
        print('ERROR [%s]: 锚点出现 %d 次' % (tag, c))
        sys.exit(1)
    sv = sv.replace(old, new, 1)


# ---------------------------------------------------------------- 1. loadAlbumIndex 末尾挂上迁移
OLD_TAIL = '''    } catch (e) {
      Log.w(TAG, '读取相册索引失败');
    }
  }'''
NEW_TAIL = '''      // 5.0.43：把老版本留在 cacheDir 里的缩略图搬到 filesDir 并补回索引
      await this.migrateThumbCache(ctx);
    } catch (e) {
      Log.w(TAG, '读取相册索引失败');
    }
  }'''
rep(OLD_TAIL, NEW_TAIL, 'load-tail')

# ---------------------------------------------------------------- 2. 新增迁移方法
NEW_METHOD = '''  /**
   * 5.0.43：把 5.0.42 及更早留在 `cacheDir/album_thumbs` 里的缩略图搬到 `filesDir/album_thumbs`，
   * 并**按文件名重建索引条目**。
   *
   * 为什么要搬：那几个版本的索引行只有 `uri|thumb`、**没写消息 id**，升级后按新格式
   * （`id|uri|thumb`）读会被当脏数据丢掉 —— 那些消息就再也找不到缩略图了。
   * 好在 `cacheThumb()` 用的文件名就是消息 id（`${id}.jpg`），文件名能反推出 key。
   *
   * ⚠️ 补出来的条目**只有缩略图、没有相册 URI**（旧行的 uri 已经找不到主人），
   *    所以点击不会跳相册 —— 但至少缩略图回来了，不会再退化成「点气泡跳文件 tab」。
   */
  private async migrateThumbCache(ctx: common.UIAbilityContext): Promise<void> {
    const oldDir: string = `${ctx.cacheDir}/album_thumbs`;
    const newDir: string = `${ctx.filesDir}/album_thumbs`;
    let names: string[] = [];
    try {
      names = fileIo.listFileSync(oldDir);
    } catch (x) {
      return; // 没有旧目录 —— 全新安装，正常情况
    }
    if (names.length === 0) {
      return;
    }
    let moved: number = 0;
    try {
      fileIo.mkdirSync(newDir);
    } catch (x) {
      // 目录已存在 —— 正常情况
    }
    for (let i: number = 0; i < names.length; i++) {
      const nm: string = names[i];
      const dot: number = nm.lastIndexOf('.');
      if (dot <= 0) {
        continue;
      }
      let id: string = nm.substring(0, dot);
      // 5.0.42 的方向兜底路径用的是 `${id}_full${ext}`，去尾巴才是消息 id
      if (id.endsWith('_full')) {
        id = id.substring(0, id.length - 5);
      }
      if (id.length === 0 || this.albumMap.has(id)) {
        continue; // 新格式里已经有了就别覆盖
      }
      try {
        fileIo.copyFileSync(`${oldDir}/${nm}`, `${newDir}/${nm}`);
        // uri 段留空：只补缩略图（旧索引里那个 uri 已经对不上这条消息了）
        this.albumMap.set(id, `|${newDir}/${nm}`);
        moved = moved + 1;
      } catch (x) {
        // 单个搬失败不影响其它
      }
    }
    // 搬完了就把旧目录清掉，别继续占着 cacheDir（那里本来就会被系统清）
    for (let i: number = 0; i < names.length; i++) {
      try {
        fileIo.unlinkSync(`${oldDir}/${names[i]}`);
      } catch (x) {
        // 忽略
      }
    }
    try {
      fileIo.rmdirSync(oldDir);
    } catch (x) {
      // 忽略
    }
    if (moved > 0) {
      Log.i(TAG, `迁移旧缩略图 ${moved} 个：cacheDir -> filesDir`);
      await this.persistAlbumIndex();
    }
  }

'''
rep('  /** 给 UI 的快照', NEW_METHOD + '  /** 给 UI 的快照', 'insert-migrate')

if sv == orig:
    print('NO CHANGE')
    sys.exit(1)

io.open(SVC, 'w', encoding='utf-8', newline='').write(sv)
print('PATCH OK')
