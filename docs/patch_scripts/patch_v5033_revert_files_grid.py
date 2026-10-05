# -*- coding: utf-8 -*-
"""
5.0.33 回退：文件页撤掉 5.0.32 的缩略图宫格，恢复成「一行一个 + 左侧 48vp 小缩略图」（即 5.0.32 之前）。
- 文件页列表渲染从「宫格 + fileItems」改回「receivedFiles 一行一个」（列表项内含 48vp 小缩略图 + 点击进画廊，原逻辑保留）
- 删掉 5.0.32 加的 mediaGrid()/mediaGridHeight() @Builder 与模块级 MediaTile/decodeVideoFrame/videoFrameCache
- 消息页保持 5.0.32（纯文件名 + 点击跳文件页），不动
- app.json5 升 5.0.33
幂等：检测宫格标记，已回退则跳过。
"""
import io

IDX = r"E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets"
APP = r"E:\lanshare-harmony\LANShareV5\AppScope\app.json5"

GRID_MARK = "5.0.32：图片/视频先排成缩略图宫格"   # 文件页渲染里宫格调用上方注释


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def write(p, s):
    io.open(p, "w", encoding="utf-8", newline="").write(s)


s = read(IDX)
if GRID_MARK not in s:
    print("ALREADY REVERTED (no grid mark in file page)")
else:
    # ---- F 回退：删宫格调用块 + fileItems 改回 receivedFiles ----
    old_f = (
        "      } else {\n"
        "        List({ space: 8 }) {\n"
        "          // 5.0.32：图片/视频先排成缩略图宫格（MediaTile 滑到才解视频首帧）\n"
        "          if (this.mediaItems.length > 0) {\n"
        "            ListItem() {\n"
        "              this.mediaGrid()\n"
        "            }\n"
        "          }\n"
        "          ForEach(this.fileItems, (f: ReceivedFile) => {\n"
    )
    new_f = (
        "      } else {\n"
        "        List({ space: 8 }) {\n"
        "          ForEach(this.receivedFiles, (f: ReceivedFile) => {\n"
    )
    assert s.count(old_f) == 1, ("F anchor count", s.count(old_f))
    s = s.replace(old_f, new_f)

    # ---- G 回退：删 mediaGrid()/mediaGridHeight() @Builder ----
    old_g = (
        "  /**\n"
        "   * 5.0.32：文件页的「图片/视频缩略图宫格」。\n"
        "   *\n"
        "   * ⚠️ 性能要点：用 `ForEach` + 自定义 `MediaTile`，**不**在主路径预热任何视频帧 ——\n"
        "   *    `Grid`/`List` 对子项是窗口化懒加载的，滑到才建 `MediaTile`、\n"
        "   *    它的 `aboutToAppear` 才去解这一条视频的首帧（模块级缓存去重，已解的不再解）。\n"
        "   *    图片直接 `Image(uri)`，框架按需解码。彻底砍掉 5.0.31「刷新就同步算全部」的卡顿。\n"
        "   */\n"
        "  @Builder\n"
        "  mediaGrid() {\n"
        "    if (this.mediaItems.length > 0) {\n"
        "      Grid() {\n"
        "        ForEach(this.mediaItems, (f: ReceivedFile) => {\n"
        "          GridItem() {\n"
        "            MediaTile({\n"
        "              path: f.path,\n"
        "              name: f.name,\n"
        "              isVideo: this.isVideoName(f.name),\n"
        "              onTap: () => this.openFileGallery(f)\n"
        "            })\n"
        "          }\n"
        "          .aspectRatio(1)\n"
        "        }, (f: ReceivedFile) => `${f.path}`)\n"
        "      }\n"
        "      .columnsTemplate('104vp 104vp 104vp')\n"
        "      .rowsGap(6)\n"
        "      .columnsGap(6)\n"
        "      .width('100%')\n"
        "      .height(this.mediaGridHeight())\n"
        "      .padding({ left: 4, right: 4 })\n"
        "    }\n"
        "  }\n"
        "\n"
        "  /** 宫格高度：3 列，每行高 = 瓦片宽(104) + 行距(6) */\n"
        "  private mediaGridHeight(): number {\n"
        "    const rows: number = Math.ceil(this.mediaItems.length / 3);\n"
        "    return rows * 104 + Math.max(0, rows - 1) * 6;\n"
        "  }\n"
        "\n"
        "  /** 目标设备胶囊。value 用设备 IP —— 与网页端下拉框的 address 保持同一套标识 */\n"
    )
    new_g = (
        "  /** 目标设备胶囊。value 用设备 IP —— 与网页端下拉框的 address 保持同一套标识 */\n"
    )
    assert s.count(old_g) == 1, ("G anchor count", s.count(old_g))
    s = s.replace(old_g, new_g)

    # ---- 模块级回退：删 MediaTile / decodeVideoFrame / videoFrameCache 整块 ----
    MOD_SENTINEL = "// ================= 5.0.32：文件页宫格的媒体瓦片"
    idx = s.find(MOD_SENTINEL)
    assert idx != -1, "module sentinel not found"
    s = s[:idx].rstrip("\n") + "\n"

    write(IDX, s)
    print("Index.ets reverted: grid removed, file page back to one-per-row + 48vp thumb")

# ---------------- app.json5 升版本 ----------------
app = read(APP)
if '"versionCode": 5000033' in app and '"versionName": "5.0.33"' in app:
    print("app.json5 already 5.0.33")
else:
    assert '"versionCode": 5000032' in app, "app.json5 未找到 5000032"
    assert '"versionName": "5.0.32"' in app, "app.json5 未找到 5.0.32"
    app = app.replace('"versionCode": 5000032', '"versionCode": 5000033')
    app = app.replace('"versionName": "5.0.32"', '"versionName": "5.0.33"')
    write(APP, app)
    print("app.json5 -> 5.0.33")

print("DONE")
