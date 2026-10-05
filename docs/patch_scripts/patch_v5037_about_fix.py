# -*- coding: utf-8 -*-
"""
5.0.37：修「关于」弹窗 —— 5.0.35 补丁把 QQ 群 / 更新地址插错了位置。

根因：两个新 Column 被插在主卡片 `Column({space:12})` 的**关闭花括号之后**
（也就是 `.width('86%')` 之后），于是：
  * 主内容 Column（标题 / 版本 / 移植说明 / 开源仓库）只剩 `.width('86%')`，
    `padding(16) / backgroundColor(C_CARD) / borderRadius / shadow` 这一串
    链式属性全被挂到了**最后那个 Column（更新地址）**上 → 主卡片没有白底，
    整个弹窗看着就是"空白背景"；
  * QQ 群 / 更新地址变成 Stack 的直接子节点，浮在半透明遮罩上 → 只剩这两个网址。

修法：按行区间整体重写 `aboutDialog()`，把两块挪进卡片 Column 内部，
链式样式挂回主 Column。

幂等：哨兵 = 「`.width('86%')` 紧跟 QQ 交流群注释」这一错排特征；
已修好（或本就没错排）时直接 SKIP。
"""
import io, sys

P = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/pages/Index.ets'

with io.open(P, encoding='utf-8', newline='') as f:
    lines = f.read().split('\n')   # 0-based；行号 = idx + 1

# ---- 1. 定位 aboutDialog() 的方法体（@Builder 后一行开始到匹配的收尾 `  }`）----
start = None
for i, ln in enumerate(lines):
    if ln == '  aboutDialog() {':
        start = i
        break
if start is None:
    print('ERROR: aboutDialog() not found')
    sys.exit(1)

end = None
for j in range(start + 1, len(lines)):
    if lines[j] == '  }':
        end = j
        break
if end is None:
    print('ERROR: aboutDialog() end not found')
    sys.exit(1)

body = '\n'.join(lines[start:end + 1])

# ---- 2. 幂等哨兵：错排特征（.width('86%') 后面紧跟 QQ 交流群块）----
BROKEN_MARK = "        .width('86%')\n\n          // ---------------- QQ 交流群"
if BROKEN_MARK not in body:
    print('ALREADY APPLIED (错排特征不存在，跳过)')
    sys.exit(0)

# ---- 3. 校验：错排块必须完整存在于方法体内 ----
for kw in ["// ---------------- QQ 交流群", "// ---------------- 更新地址",
           "// ---------------- 开源仓库（可复制）----------------",
           ".backgroundColor('#80000000')"]:
    if kw not in body:
        print('ERROR: 缺少预期关键字 ->', kw)
        sys.exit(1)

# ---- 4. 构造修正后的完整方法体 ----
new_body = """  aboutDialog() {
    if (this.showAbout) {
      Stack() {
        Column()
          .width('100%')
          .height('100%')
          .onClick(() => {
            this.showAbout = false;
          })

        // ⚠️ 5.0.37：QQ 群 / 更新地址两块必须写在**这个 Column 内部**。
        // 5.0.35 曾把它们插到本 Column 的收尾花括号之后，导致
        // padding / backgroundColor / borderRadius / shadow 这些链式属性
        // 被挂到最后一个子块上 —— 主卡片丢白底，只剩两个网址浮在遮罩上。
        Column({ space: 12 }) {
          // ---------------- 标题 + 关闭 ----------------
          Row() {
            Text('关于 LANShare')
              .fontSize(16)
              .fontWeight(FontWeight.Bold)
              .fontColor(C_TEXT)
              .layoutWeight(1)
            Text('关闭')
              .fontSize(13)
              .fontColor(C_PRIMARY)
              .onClick(() => {
                this.showAbout = false;
              })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          // ---------------- 版本号 ----------------
          Row({ space: 8 }) {
            Text('版本')
              .fontSize(13)
              .fontColor(C_SUB)
            Text(this.aboutVer)
              .fontSize(13)
              .fontWeight(FontWeight.Medium)
              .fontColor(C_TEXT)
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          // ---------------- 移植说明 ----------------
          Text('本应用是基于「梦醒了」大佬的开源项目 LANShare 移植的鸿蒙（HarmonyOS）版本。'
            + '协议实现与核心代码均来自原开源项目，在此致谢。')
            .fontSize(13)
            .fontColor(C_TEXT)
            .width('100%')

          // ---------------- 开源仓库（可复制）----------------
          Column({ space: 6 }) {
            Text('开源仓库')
              .fontSize(11)
              .fontColor(C_SUB)
              .width('100%')
            Row({ space: 8 }) {
              Text(ABOUT_REPO)
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .layoutWeight(1)
                .maxLines(2)
                .wordBreak(WordBreak.BREAK_ALL)
              Text('复制')
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .onClick(() => {
                  this.copyRepo();
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }
          .width('100%')
          .padding(10)
          .backgroundColor('#F6F8FB')
          .borderRadius(10)

          // ---------------- QQ 交流群（可复制）----------------
          Column({ space: 6 }) {
            Text('QQ 交流群')
              .fontSize(11)
              .fontColor(C_SUB)
              .width('100%')
            Row({ space: 8 }) {
              Text('538809905')
                .fontSize(13)
                .fontColor(C_TEXT)
                .layoutWeight(1)
              Text('复制')
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .onClick(() => {
                  this.copyText('538809905');
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }
          .width('100%')
          .padding(10)
          .backgroundColor('#F6F8FB')
          .borderRadius(10)

          // ---------------- 更新地址（网盘，可复制）----------------
          Column({ space: 6 }) {
            Text('更新地址')
              .fontSize(11)
              .fontColor(C_SUB)
              .width('100%')
            Row({ space: 8 }) {
              Text(ABOUT_UPDATE)
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .layoutWeight(1)
                .maxLines(2)
                .wordBreak(WordBreak.BREAK_ALL)
              Text('复制')
                .fontSize(12)
                .fontColor(C_PRIMARY)
                .onClick(() => {
                  this.copyText(ABOUT_UPDATE);
                })
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }
          .width('100%')
          .padding(10)
          .backgroundColor('#F6F8FB')
          .borderRadius(10)
        }
        .width('86%')
        .constraintSize({ maxHeight: '82%' })
        .padding(16)
        .backgroundColor(C_CARD)
        .borderRadius(14)
        .shadow({ radius: 24, color: '#33000000', offsetX: 0, offsetY: 8 })
        .onClick(() => {
          // 吃掉点击，避免穿透到遮罩把弹窗关掉
        })
      }
      .width('100%')
      .height('100%')
      .backgroundColor('#80000000')
    }
  }"""

# ---- 5. 括号 / 结构自检：新旧体的花括号增量必须一致 ----
old_delta = body.count('{') - body.count('}')
new_delta = new_body.count('{') - new_body.count('}')
if old_delta != new_delta:
    print('ERROR: 花括号增量不一致 old=%d new=%d' % (old_delta, new_delta))
    sys.exit(1)

# ---- 6. 统一落盘 ----
out = lines[:start] + new_body.split('\n') + lines[end + 1:]
with io.open(P, 'w', encoding='utf-8', newline='') as f:
    f.write('\n'.join(out))

print('OK: aboutDialog() 重写完成（原 %d 行 -> 新 %d 行）' % (end - start + 1, len(new_body.split('\n'))))
