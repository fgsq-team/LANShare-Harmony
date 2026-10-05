# -*- coding: utf-8 -*-
"""
5.0.45：点击「历史图片」消息 -> 补存进相册 -> 跳系统相册。

背景：
  5.0.38 起收到的图片会自动存相册并记 URI，点气泡能直接跳系统相册。
  但**更早的历史图片**当时没有 URI（沙箱原图已删，只剩 320px 缓存缩略图），
  点击只能回应用内预览 / 跳「文件」页。

方案（不弹权限框，复用已有的免权限通道）：
  点历史图 -> 用 showAssetsCreationDialog 把缓存缩略图补存进相册（弹一次系统确认框）
          -> 拿到 URI 后记进索引 -> openInGallery(uri) 跳系统相册；
  取消 / 失败 -> 回退应用内预览（不阻断）。
  ⚠️ 存过一次之后索引里就有 URI 了，以后点击直接跳，不再弹框。

改动：
  1) saveImageToAlbum 返回 boolean（成功 true / 取消或失败 false）；
  2) saveImageToAlbum 内部：若源文件**就是**该消息已有的缓存缩略图，跳过 cacheThumb
     （否则会「自己解码自己、写到同一路径」，有把缓存图写坏的风险）；
  3) 新增 historyToAlbum()；
  4) onFileBubbleClick 末尾分支改走 historyToAlbum。
"""
import io
import sys

PAGE = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'

SENTINEL = 'private async historyToAlbum('


def read(p):
    return io.open(p, encoding='utf-8', newline='').read()


def write(p, s):
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


def main():
    s = read(PAGE)
    if SENTINEL in s:
        print('ALREADY APPLIED')
        return

    # ---- 1) saveImageToAlbum 签名改为返回 boolean ----
    old1 = "  private async saveImageToAlbum(path: string, name: string, id: string = ''): Promise<void> {"
    new1 = ("  /**\n"
            "   * @returns true = 已存进相册；false = 用户取消或保存失败\n"
            "   */\n"
            "  private async saveImageToAlbum(path: string, name: string, id: string = ''): Promise<boolean> {")
    assert s.count(old1) == 1, f'[1] saveImageToAlbum 签名出现 {s.count(old1)} 次'
    s = s.replace(old1, new1)

    # ---- 2) 各处 return 改成带返回值 ----
    old2 = """    if (path.length === 0) {
      this.toast('找不到源文件');
      return;
    }"""
    new2 = """    if (path.length === 0) {
      this.toast('找不到源文件');
      return false;
    }"""
    assert s.count(old2) == 1, f'[2] 空路径分支出现 {s.count(old2)} 次'
    s = s.replace(old2, new2)

    old3 = """      if (uris.length === 0) {
        // 用户点了取消 —— 系统返回空数组，不是错误
        this.toast('已取消保存');
        return;
      }"""
    new3 = """      if (uris.length === 0) {
        // 用户点了取消 —— 系统返回空数组，不是错误
        this.toast('已取消保存');
        return false;
      }"""
    assert s.count(old3) == 1, f'[3] 取消分支出现 {s.count(old3)} 次'
    s = s.replace(old3, new3)

    # ---- 3) 写索引那段：源就是缓存缩略图时跳过 cacheThumb，并 return true ----
    old4 = """      // 5.0.44：手动保存也要缓存缩略图并记相册 URI，否则沙箱原图一删就丢。
      if (msg.startsWith('已保存') && id.length > 0) {
        try {
          const thumb: string = await this.cacheThumb(ctx, path, id);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(id, uris[0], thumb, rot);
        } catch (x) {
          Log.w(TAG, `手动保存后缓存缩略图失败: ${path}`);
        }
      }
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `存相册失败: ${err.code} ${err.message}`);
      this.toast(`保存失败：${err.message}`);
    }
  }"""
    new4 = """      if (!msg.startsWith('已保存')) {
        return false;
      }
      // 5.0.44：手动保存也要缓存缩略图并记相册 URI，否则沙箱原图一删就丢。
      if (id.length > 0) {
        try {
          // 5.0.45：源文件**就是**这条消息已有的缓存缩略图时（历史图补存这条路径），
          //         不能再 cacheThumb 一遍 —— 那等于「自己解码自己再写回同一路径」，
          //         有把缓存图写坏的风险。直接用现成的那份。
          const oldThumb: string = this.albumPart(id, 1);
          const thumb: string = (oldThumb.length > 0 && oldThumb === path)
            ? path : await this.cacheThumb(ctx, path, id);
          const rot: number = this.service.rotOf(thumb) ?? 0;
          await this.service.setAlbumIndex(id, uris[0], thumb, rot);
        } catch (x) {
          Log.w(TAG, `手动保存后缓存缩略图失败: ${path}`);
        }
      }
      return true;
    } catch (e) {
      const err: BusinessError = e as BusinessError;
      Log.w(TAG, `存相册失败: ${err.code} ${err.message}`);
      this.toast(`保存失败：${err.message}`);
      return false;
    }
  }

  /**
   * 5.0.45：点**历史图片**气泡 -> 补存进相册 -> 跳系统相册。
   *
   * 历史图片（5.0.38 之前收的，或当时自动存相册关着）索引里没有相册 URI，
   * 沙箱原图往往也已经删了，只剩下 `album_thumbs/<id>.jpg` 这份 320px 缓存图。
   * 这里把它补存进相册，拿到 URI 记回索引 —— **存过一次之后就永远能直接跳**，
   * 不用再弹第二次框。用户取消或保存失败则回退应用内预览，不阻断。
   */
  private async historyToAlbum(m: ChatMessage, thumb: string): Promise<void> {
    const ok: boolean = await this.saveImageToAlbum(thumb, m.content, m.id);
    if (ok) {
      const uri: string = this.albumPart(m.id, 0);
      if (uri.length > 0) {
        this.openInGallery(uri);
        return;
      }
    }
    // 没存成 / 没拿到 URI -> 还是用缓存图在应用内看，别把用户晾在那
    this.openMediaPreview(thumb, m.content, m.id);
  }"""
    assert s.count(old4) == 1, f'[4] 写索引段出现 {s.count(old4)} 次'
    s = s.replace(old4, new4)

    # ---- 4) onFileBubbleClick 末尾分支改走 historyToAlbum ----
    old5 = """    // 5.0.44：旧消息沙箱原图已删、只有缓存缩略图时，点气泡用缩略图预览，
    //         而不是直接跳「文件」页（旧数据没有相册 URI 是预期行为）。
    const thumb: string = this.albumPart(m.id, 1);
    if (thumb.length > 0 && this.isMediaName(thumb)) {
      this.openMediaPreview(thumb, m.content, m.id);
      return;
    }
    this.openFileTab();"""
    new5 = """    // 5.0.45：旧消息沙箱原图已删、只剩缓存缩略图 -> 补存进相册再跳过去。
    //         历史图片本来就不在相册里，所以第一次点会弹一次系统确认框；
    //         存成之后索引里就有了 URI，以后点击直接跳相册，不再弹框。
    const thumb: string = this.albumPart(m.id, 1);
    if (thumb.length > 0 && this.isMediaName(thumb)) {
      this.historyToAlbum(m, thumb).catch(() => {
        this.openMediaPreview(thumb, m.content, m.id);
      });
      return;
    }
    this.openFileTab();"""
    assert s.count(old5) == 1, f'[5] onFileBubbleClick 末尾出现 {s.count(old5)} 次'
    s = s.replace(old5, new5)

    write(PAGE, s)
    print('OK: 5.0.45 补丁已应用')


if __name__ == '__main__':
    main()
