# -*- coding: utf-8 -*-
"""
v5.1.4 两处修复（vivi 21:28）：

## ① 收到多个文件仍只有一个气泡 → 每个文件一条消息
根因：`LanService.appendFileChat` 的**非媒体分支**（:2234）把整批塞进**一条**消息：
    this.appendChat(incoming, peerName, peerIp, label, source, 'file', names.join('\\n'));
- `content` = label（「3 个文件」）、`files` = 全部文件名、`batchId` = **空串**
⇒ `buildChatGroups` 只按 `batchId` 聚合，空串 ⇒ 一条消息 ⇒ **一个气泡**

修法：非媒体也**每个文件一条消息**，但**不给 batchId** ⇒
`buildChatGroups` 的 `if (m.batchId.length > 0 && ...)` 不成立 ⇒ **各自成气泡**。

⚠️ **绝不能给非媒体共 batchId** —— 那会走进 `groupAllMedia` 的判定，
  而 `allMedia` 对 zip 返回 false ⇒ `isMedia` 为 false ⇒ 宫格不显示 ⇒
  界面看起来没变。**「拆消息」与「聚合成宫格」是两个独立开关。**

★ 顺带把 5.1.3 的判据受益面扩大：现在每条消息 `files` 只有 1 个名字，
  `msgCarriesFileName` 的逐行匹配不再需要，但**保留多行支持**
  （兼容历史数据 —— 旧版存的消息仍是多行 `files`）。

## ② 关于页返回应回软件界面，不是手机桌面
根因：`onBackPress` 处理了 6 个弹窗（confirm / imgPreview / fileSelect /
chatSelect / showQr / pickStep），**唯独漏了 `showAbout`**（实测命中 0 次）
⇒ 落到末尾 `return false` 交还系统 ⇒ **退出应用**。

修法：在 `onBackPress` 里加 `showAbout` 分支。
⚠️ 顺序：放在 `pickStep` 之后即可（它们互斥，不影响既有顺序语义）。
★ 顺带加一条**兜底自检注释**：新增弹窗时必须同步这里 ——
  这是「自绘弹窗 + 系统返回」的固有陷阱，漏一个就等于「按返回退出应用」。
"""
import io
import sys
import os

IDX = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\pages\Index.ets'
SVC = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\LanService.ets'
VER = r'E:\lanshare-harmony\LANShareV5\AppScope\app.json5'
BAK = r'E:\lanshare-harmony\LANShareV5\docs\backups'

# =====================================================================
# 服务端：非媒体也逐个建消息（但不给 batchId）
# =====================================================================
OLDS1 = """    this.appendChat(incoming, peerName, peerIp, label, source, 'file', names.join('\\n'));
  }"""
NEWS1 = """    // ★★ 5.1.4（vivi 21:28）：**非媒体也逐个文件建消息** —— vivi 要求
    //   「收到多个文件就生成多个气泡，不要再合并为一个气泡」。
    //
    //   此前这里把整批塞进**一条**消息（content=label、files=全部名字、batchId=空）
    //   ⇒ `buildChatGroups` 只按 batchId 聚合 ⇒ 空串 ⇒ **一个气泡**。
    //
    //   ⚠️⚠️ **绝不能顺手给非媒体共 batchId**：`groupAllMedia` 走 `allMedia(names)`，
    //   而 `allMedia` 对 zip/pdf 返回 **false** ⇒ `isMedia=false` ⇒ 不走宫格
    //   ⇒ **界面看起来完全没变**。**「拆成多条消息」与「聚合成一个宫格」是两个
    //   独立开关**（前者控消息条数，后者控渲染形式）—— 5.0.55 只把前者用于媒体。
    //   ⇒ 正确做法：**拆消息、batchId 留空**。
    //
    //   媒体批在上面已经 return 了，所以这里必然**不含**图片/视频。
    if (names.length > 1) {
      for (let i: number = 0; i < names.length; i++) {
        // 每条：content = 自己的文件名（气泡显示它）、files = 自己的文件名
        // （5.1.3 的 `msgCarriesFileName` 靠它反查）、batchId = 空（各自成气泡）
        this.appendChat(incoming, peerName, peerIp, names[i], source, 'file', names[i]);
      }
      return;
    }
    this.appendChat(incoming, peerName, peerIp, label, source, 'file', names.join('\\n'));
  }"""

# =====================================================================
# 页面：onBackPress 加 showAbout
# =====================================================================
OLDP1 = """    if (this.pickStep > 0) {
      this.pickStep = 0;
      return true;
    }
    return false;
  }"""
NEWP1 = """    if (this.pickStep > 0) {
      this.pickStep = 0;
      return true;
    }
    // ★ 5.1.4（vivi 21:28）：「关于」弹窗也必须接住返回键。
    //   此前 `onBackPress` 处理了 6 个弹窗却**漏了它**（实测命中 0 次）
    //   ⇒ 落到末尾 `return false` 交还系统 ⇒ **按返回直接退出应用到桌面**。
    //   ⚠️ 自绘弹窗（`showXxx`）必须逐个登记到这里 —— 这是本项目的固有陷阱：
    //   **漏一个 = 用户按返回就退出应用**，而界面上弹窗还开着。
    if (this.showAbout) {
      this.showAbout = false;
      return true;
    }
    return false;
  }"""

# =====================================================================
# 版本号
# =====================================================================
OLDV = '"versionCode": 5000103'
NEWV = '"versionCode": 5000104'

# =====================================================================
# 执行
# =====================================================================
s_svc = io.open(SVC, encoding='utf-8').read()
s_idx = io.open(IDX, encoding='utf-8').read()
s_ver = io.open(VER, encoding='utf-8').read()

if '5.1.4' in s_svc:
    print('ALREADY APPLIED')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'LanService.ets.v514pre'), 'w', encoding='utf-8', newline='\n').write(s_svc)
io.open(os.path.join(BAK, 'Index.ets.v514pre'), 'w', encoding='utf-8', newline='\n').write(s_idx)
io.open(os.path.join(BAK, 'app.json5.v514pre'), 'w', encoding='utf-8', newline='\n').write(s_ver)
print('备份完成（3 个文件）')

# ---- 服务端 ----
n = s_svc.count(OLDS1)
assert n == 1, 'S1 锚点命中 %d 次（应为 1）' % n
s_svc = s_svc.replace(OLDS1, NEWS1, 1)

# ---- 页面 ----
n = s_idx.count(OLDP1)
assert n == 1, 'P1 锚点命中 %d 次（应为 1）' % n
s_idx = s_idx.replace(OLDP1, NEWP1, 1)

assert s_ver.count(OLDV) == 1
s_ver = s_ver.replace(OLDV, NEWV, 1)
assert s_ver.count('"versionName": "5.1.3"') == 1
s_ver = s_ver.replace('"versionName": "5.1.3"', '"versionName": "5.1.4"', 1)

# ---------------- 不变量 ----------------
# ① 非媒体逐个建消息、batchId 留空
assert 'if (names.length > 1) {' in s_svc
assert "this.appendChat(incoming, peerName, peerIp, names[i], source, 'file', names[i]);" in s_svc
# ⚠️ 绝不能出现「非媒体那行传了 batchId」。
#    判据要说清：`names[i] + bid` 这一行**本来就该存在**（媒体批，5.0.55 就有的），
#    所以不能只查「有没有 names[i] 且带 bid」—— 那会把媒体那行也当成违规。
#    正确判据 = **数「appendChat + names[i] + 带 bid」的行数**：
#    改后应当**恰好 1 行**（媒体批那条）；若 ≥2 就说明非媒体也被塞了 batchId。
n_bid = len([l for l in s_svc.split('\n')
             if 'appendChat' in l and 'names[i]' in l and l.rstrip().endswith(', bid);')])
assert n_bid == 1, '带 batchId 的 names[i] 行应恰好 1 行（媒体批），实际 %d 行' % n_bid
# 且非媒体那行必须**不带** batchId
assert "this.appendChat(incoming, peerName, peerIp, names[i], source, 'file', names[i]);" in s_svc
# 媒体批那行必须原样保留
assert "this.appendChat(true, peerName, peerIp, names[i], source, 'file', names[i], bid);" in s_svc
# ② onBackPress 加了 showAbout，且在 return false 之前
i_back = s_idx.find('onBackPress(): boolean {')
j_back = s_idx.find('\n  }', i_back)
seg = s_idx[i_back:j_back]
assert 'if (this.showAbout) {' in seg, 'showAbout 分支不在 onBackPress 内'
assert seg.index('if (this.showAbout) {') < seg.rindex('return false'), 'showAbout 在 return false 之后'
# 既有 6 个分支都还在
for b in ('confirmVisible', 'imgPreview', 'fileSelectMode', 'chatSelectMode', 'showQr', 'pickStep'):
    assert 'this.%s' % b in seg, '既有返回分支被破坏: %s' % b
# 5.1.3 / 5.1.2 / 5.1.1 成果仍在
assert 'private msgCarriesFileName(' in s_idx
assert s_idx.count('this.markMessagesLocal(f.name, Index.HINT_LOCAL_SAVED);') == 1
assert "private static readonly HINT_FILE: string = '点击查看';" in s_idx
assert 'private diagSnapshot(' not in s_idx and 'this.diagSnapshot(' not in s_idx

io.open(SVC, 'w', encoding='utf-8', newline='\n').write(s_svc)
io.open(IDX, 'w', encoding='utf-8', newline='\n').write(s_idx)
io.open(VER, 'w', encoding='utf-8', newline='\n').write(s_ver)
print('OK  LanService.ets %d chars' % len(s_svc))
print('OK  Index.ets     %d chars' % len(s_idx))
print('OK  versionCode 5000103 -> 5000104 / 5.1.4')
