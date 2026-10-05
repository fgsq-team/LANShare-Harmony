# -*- coding: utf-8 -*-
"""
5.0.45：历史图片点气泡 -> 跳系统看图器（而非文件 tab / 应用内预览）。

根因回顾：
- 5.0.43 之前 albumIndex 持久化把 key 丢了，升级后历史图片只恢复了 `id|thumb`，
  没有相册 URI（`albumPart(m.id,0)` 为空）。
- 已存进相册的历史图，沙箱原图在 5.0.39 已被删，本地只剩 320px 缓存缩略图。
- 所以这些历史图点气泡既不能跳相册 grid（没 URI），也不该静默跳「文件」页。

修法：
- `onFileBubbleClick()`：没有相册 URI 时，用「系统看图器」(`viewData` + 沙箱文件 URI
  + `FLAG_AUTH_READ_URI_PERMISSION` 临时读授权) 直接打开本地文件：原图还在就用原图，
  否则用 320px 缓存缩略图。不写相册、不弹框、不丢原图。
- 两个包名都试（HOS `com.huawei.hmos.photos` / OpenHarmony `com.ohos.photos`），
  都失败才回退应用内预览（绝不跳文件 tab）。
- 已在相册 URI 的新图仍走 `openInGallery()` 跳相册 grid（行为不变）。
"""
import io

PAGE = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'
APP  = r'E:/lanshare-harmony/LANShareV5/AppScope/app.json5'

SENTINEL = '5.0.45：历史图片点气泡 -> 跳系统看图器'

def read(p):
    return io.open(p, encoding='utf-8', newline='').read()

def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='').write(s)

def patch_import(s):
    old = "import { common, bundleManager, Want } from '@kit.AbilityKit';"
    new = "import { common, bundleManager, Want, wantConstant } from '@kit.AbilityKit';"
    assert s.count(old) == 1, f'import 行出现 {s.count(old)} 次'
    return s.replace(old, new)

def patch_onclick(s):
    old = """  private onFileBubbleClick(m: ChatMessage): void {
    const album: string = this.albumPart(m.id, 0);
    if (album.length > 0) {
      this.openInGallery(album);
      return;
    }
    const ps: string[] = this.mediaPathsOf(m.id);
    if (ps.length > 1) {
      this.openChatGallery(m.id, 0);
      return;
    }
    if (ps.length === 1 && this.isMediaName(ps[0])) {
      this.openMediaPreview(ps[0], m.content, m.id);
      return;
    }
    const p: string = this.chatMediaPaths.get(m.id) ?? '';
    if (p.length > 0 && this.isMediaName(p)) {
      this.openMediaPreview(p, m.content, m.id);
      return;
    }
    // 5.0.44：旧消息沙箱原图已删、只有缓存缩略图时，点气泡用缩略图预览，
    //         而不是直接跳「文件」页（旧数据没有相册 URI 是预期行为）。
    const thumb: string = this.albumPart(m.id, 1);
    if (thumb.length > 0 && this.isMediaName(thumb)) {
      this.openMediaPreview(thumb, m.content, m.id);
      return;
    }
    this.openFileTab();
  }"""
    new = """  private onFileBubbleClick(m: ChatMessage): void {
    const album: string = this.albumPart(m.id, 0);
    if (album.length > 0) {
      // 已在相册（5.0.44+ 收到的图都记了 URI）-> 直接跳系统相册 grid
      this.openInGallery(album);
      return;
    }
    const ps: string[] = this.mediaPathsOf(m.id);
    if (ps.length > 1) {
      // 多条媒体 -> 应用内画廊
      this.openChatGallery(m.id, 0);
      return;
    }
    // 5.0.45：历史图片（没记到相册 URI）点气泡 -> 用系统看图器打开本地文件。
    // 沙箱原图还在（当时自动存相册关着 / 5.0.38 之前收的）就用原图，
    // 否则用 320px 缓存缩略图。不写相册、不弹框、不丢原图；看图器打不开才回退预览。
    const local: string = (ps.length === 1) ? ps[0] : (this.chatMediaPaths.get(m.id) ?? '');
    const src: string = (local.length > 0 && this.isMediaName(local)) ? local : this.albumPart(m.id, 1);
    if (src.length > 0 && this.isMediaName(src)) {
      this.openLocalImage(src, m);
      return;
    }
    this.openFileTab();
  }"""
    assert s.count(old) == 1, f'onFileBubbleClick 出现 {s.count(old)} 次'
    assert s.count(new) == 0, '5.0.45 已应用'
    return s.replace(old, new)

def patch_openlocal(s):
    old = """      });
    });
  }

  /** 把文件名压成系统允许的相册 title（非法字符统一换成下划线） */"""
    new = """      });
  }

  /**
   * 5.0.45：用系统看图器打开**本地沙箱文件**（原图或缓存缩略图）。
   *
   * 场景：历史图片没记到相册 URI（5.0.43 之前索引 key 丢了），点气泡时本地还有文件，
   *   直接调系统看图器打开它 = 「跳到相册看」，不写相册、不弹框、不丢原图。
   *
   * ⚠️ 必须给沙箱文件 URI 临时读授权（`wantConstant.Flags.FLAG_AUTH_READ_URI_PERMISSION`），
   *   否则系统相册/看图器读不到我们的沙箱文件（会直接 reject，无界面提示）。
   * ⚠️ 两个包名都要试（HOS `com.huawei.hmos.photos` / OpenHarmony `com.ohos.photos`），
   *   都失败（极少见）时回退应用内预览，绝不静默跳到「文件」页。
   */
  private openLocalImage(path: string, m: ChatMessage): void {
    const ctx: common.UIAbilityContext =
      this.getUIContext().getHostContext() as common.UIAbilityContext;
    const uri: string = fileUri.getUriFromPath(path);
    const p: Record<string, Object> = { 'uri': uri };
    const w1: Want = {
      action: 'ohos.want.action.viewData',
      uri: uri,
      parameters: p,
      flags: wantConstant.Flags.FLAG_AUTH_READ_URI_PERMISSION,
      bundleName: 'com.huawei.hmos.photos',
      abilityName: 'com.huawei.hmos.photos.MainAbility'
    };
    ctx.startAbility(w1).then(() => {
      Log.i(TAG, `已用系统看图器打开: ${Index.baseName(path)}`);
    }).catch(() => {
      const w2: Want = {
        action: 'ohos.want.action.viewData',
        uri: uri,
        parameters: p,
        flags: wantConstant.Flags.FLAG_AUTH_READ_URI_PERMISSION,
        bundleName: 'com.ohos.photos',
        abilityName: 'com.ohos.photos.MainAbility'
      };
      ctx.startAbility(w2).then(() => {
        Log.i(TAG, `已用系统看图器打开(OpenHarmony): ${Index.baseName(path)}`);
      }).catch((e: BusinessError) => {
        Log.w(TAG, `系统看图器打开失败，回退应用内预览: ${e.code} ${e.message}`);
        this.openMediaPreview(path, m.content, m.id);
      });
    });
  }

  /** 把文件名压成系统允许的相册 title（非法字符统一换成下划线） */"""
    assert s.count(old) == 1, f'openInGallery 结尾锚点出现 {s.count(old)} 次'
    assert s.count(new) == 0, 'openLocalImage 已存在'
    return s.replace(old, new)

def patch_designlog(s):
    old = "   * | 沙箱副本删了缩略图还会在吗 | 会。`cacheThumb()` 在删之前把小图写进 `filesDir/album_thumbs/<msgid>.jpg`，并记下真实宽高比；`bubbleMediaPath()` 优先用沙箱那份、没了就用缓存图。⚠️ 为什么不读相册 URI：那是个**写授权** URI，回头去读不一定读得到 |"
    new = old + "\n" + \
    "   * | 5.0.45：历史图片点气泡跳哪 | 没记到相册 URI 的历史图（5.0.43 前索引 key 丢了）-> 用**系统看图器**打开本地文件（原图优先，否则 320px 缓存缩略图），不写相册、不弹框；看图器打不开才回退应用内预览。已在相册的新图仍走 `openInGallery` 跳相册 grid |"
    assert s.count(old) == 1, f'设计日志锚点出现 {s.count(old)} 次'
    assert s.count('5.0.45：历史图片点气泡跳哪') == 0, '设计日志已加'
    return s.replace(old, new)

def patch_version(app):
    old = '    "versionCode": 5000044,\n    "versionName": "5.0.44",'
    new = '    "versionCode": 5000045,\n    "versionName": "5.0.45",'
    assert app.count(old) == 1, f'版本号出现 {app.count(old)} 次'
    return app.replace(old, new)

def main():
    s = read(PAGE)
    if SENTINEL in s:
        print('ALREADY APPLIED 5.0.45'); return
    s = patch_import(s)
    s = patch_onclick(s)
    s = patch_openlocal(s)
    write(PAGE, s)
    app = read(APP)
    app = patch_version(app)
    write(APP, app)
    print('PATCHED 5.0.45 OK')

if __name__ == '__main__':
    main()
