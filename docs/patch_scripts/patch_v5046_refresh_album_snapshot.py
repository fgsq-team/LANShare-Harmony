# -*- coding: utf-8 -*-
"""
5.0.46：修「历史图片不管点几次都跳保存弹窗」。

根因：
  `albumPart()` 读的是**页面本地快照** `this.albumIndex`（@State Map），它只在
  「启动 loadAlbumIndex 后」和「自动存相册批次完成后」两处刷新。
  `service.setAlbumIndex()` 写的是 service 里的 albumMap —— 页面快照不知道。

  于是 5.0.45 的 historyToAlbum：补存成功 -> `albumPart(m.id,0)` 查的还是旧快照
  -> 空 -> 不跳相册、回退预览；下次点击照样走补存分支 -> **每次都弹保存框**。
  （手动「存相册」按钮也有同样的 bug，只是那个场景用户不会立刻点气泡验证，
   所以一直没暴露 —— 和 5.0.39「1 张不弹 2 张才弹」一样，都是"刷新索引"没接上。）

修法：
  `saveImageToAlbum()` 成功路径 return true 之前，把页面快照刷新成 service 最新值。
  albumIndex 是 @State，刷新后气泡角标（"已存入相册 · 点击打开 ›"）也会立即重绘。
"""
import io

PAGE = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'
APP = r'E:/lanshare-harmony/LANShareV5/AppScope/app.json5'

SENTINEL = '5.0.46：索引写进 service 了'


def main():
    s = io.open(PAGE, encoding='utf-8', newline='').read()
    if SENTINEL in s:
        print('ALREADY APPLIED')
        return

    old = """      return true;
    } catch (e) {"""
    new = """      // 5.0.46：索引写进 service 了，但**页面快照还停在旧值** ——
      //         不刷新的话 albumPart(m.id,0) 一直查不到 URI，
      //         历史图每次点击都会再弹一次保存框（5.0.45 真机复现）。
      this.albumIndex = this.service.albumSnapshot();
      return true;
    } catch (e) {"""
    assert s.count(old) == 1, f'[1] count={s.count(old)}'
    s = s.replace(old, new)
    io.open(PAGE, 'w', encoding='utf-8', newline='\n').write(s)

    a = io.open(APP, encoding='utf-8', newline='').read()
    oldv = '"versionCode": 5000045,\n    "versionName": "5.0.45",'
    newv = '"versionCode": 5000046,\n    "versionName": "5.0.46",'
    assert a.count(oldv) == 1, f'[2] app.json5 count={a.count(oldv)}'
    io.open(APP, 'w', encoding='utf-8', newline='\n').write(a.replace(oldv, newv))
    print('OK: 5.0.46 已应用（页面快照刷新 + 版本号）')


if __name__ == '__main__':
    main()
