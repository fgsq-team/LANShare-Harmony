# -*- coding: utf-8 -*-
"""5.0.38：版本号 + 文件头变更记录（幂等）。"""
import io, sys

IDX = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'
APP = r'E:/lanshare-harmony/LANShareV5/AppScope/app.json5'

idx = io.open(IDX, encoding='utf-8', newline='').read()

if '## 2026-10-02 第十四轮（5.0.38' in idx:
    print('SKIP: 变更记录已存在')
else:
    anchor = '\n */\nimport { common, bundleManager }'
    if idx.count(anchor) != 1:
        print('ERROR: 头部注释收尾锚点不唯一')
        sys.exit(1)
    block = (
        '\n *\n'
        ' * ## 2026-10-02 第十四轮（5.0.38：收到图片/视频自动存相册）\n'
        ' * | 诉求 | 落法 |\n'
        ' * |---|---|\n'
        ' * | 像捷传那样，收到的图片视频直接进相册 | 复用已有的 `showAssetsCreationDialog`（**免权限**），'
        '把它从「手动长按」接到**接收完成那一刻**：`onSnapshot` 聊天条数变化分支捕获 `oldCount` → '
        '`autoSaveNewMedia()` 挑出新增的「收到 + kind=file」记录里能解析出沙箱路径的图/视频 → '
        '`autoSaveAlbumBatch()` **整批一次弹框**逐个 `ExportService.copyTo`。'
        '⚠️ 用 `timeMs` 60 秒新鲜度挡掉「启动 restoreChat 灌历史」那次条数跳变，'
        '否则每次开 App 都会把历史图视频重弹一遍保存框 |\n'
        ' * | 不想被自动打扰怎么办 | 设置区新增「收到图片/视频自动存相册」开关（默认开），'
        '持久化到 LanService 的 `PREF_CFG` |\n'
        ' * | 为什么不用 WRITE_IMAGEVIDEO | 它是**受限权限**，普通应用申请不到。'
        '`showAssetsCreationDialog` 不需要任何权限声明，代价只是要弹一次系统确认框。'
        '前提：module.json5 的 abilities 必须配 label 和 icon，否则确认框显示不出应用名 |\n'
        ' * | ⚠️ 已知边界 | 手机形态**没有**静默直写系统「下载」目录的通道 '
        '（`READ_WRITE_DOWNLOAD_DIRECTORY` 官方限定仅 2in1 / 平板；'
        '`Environment.getUserDownloadDir()` 依赖的 SysCap 也仅 2in1）。'
        '非图片视频的文件仍需走「另存为」Picker |\n'
        ' */\nimport { common, bundleManager }')
    idx = idx.replace(anchor, block, 1)
    io.open(IDX, 'w', encoding='utf-8', newline='').write(idx)
    print('WROTE Index.ets changelog')

app = io.open(APP, encoding='utf-8', newline='').read()
if '"versionCode": 5000038' in app:
    print('SKIP: 版本号已是 5.0.38')
else:
    if app.count('"versionCode": 5000037') != 1:
        print('ERROR: 版本号锚点不唯一')
        sys.exit(1)
    app = app.replace('"versionCode": 5000037', '"versionCode": 5000038', 1)
    app = app.replace('"versionName": "5.0.37"', '"versionName": "5.0.38"', 1)
    io.open(APP, 'w', encoding='utf-8', newline='').write(app)
    print('WROTE app.json5 -> 5.0.38')
print('DONE')
