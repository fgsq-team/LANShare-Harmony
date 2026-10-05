# -*- coding: utf-8 -*-
"""追加 5.0.52 收尾（交付 + skill 归档）到当日工作日志。幂等：哨兵判重。"""
import io, sys

P = r'E:\lanshare项目\.workbuddy\memory\2026-10-02.md'
SENTINEL = '### 13:40 5.0.52 交付与知识归档'

ADD = '''

### 13:40 5.0.52 交付与知识归档

- 构建 `BUILD SUCCESSFUL in 41s`；解包 `ets/modules.abc` 搜到本轮全部运行时串
  （`本机无法校验相册状态，已关闭「已删除」提示`、`信任=`、`刚写入的相册资产被判「不存在」`、
  `相册探活：`、`判定不出（按还在处理）`、`已不存在`、`该文件已从相册删除`）；
  `module.json` 报 5.0.52 / 5000052。
- 产物 `E:\\lanshare-harmony\\LANShare-5.0.52.hap`（2,360,708 B）。commit `473d3f5`，tag `v5.0.52`。
- `hdc list targets` 仍 `[Empty]`（无设备）→ 按约定改走**夸克网盘**交付，未卡在推送。
- **知识归档**：5.0.52 的两条通用结论写进 skill `harmonyos-arkui-ui-pitfalls`
  （第二十六节「一批多个文件 = 一条消息 ⇒ 记账 key 必须带媒体序号」、
  第二十七节「相册 URI 是写授权，资产在不在无法自证 ⇒ 用刚写入的资产现场自校准」），
  并给 description 补了触发词。补丁脚本 `skill_append_arkui_26_27.py` / `skill_desc_trigger_5052.py`（均幂等）。
- MEMORY.md 超标（15,371 B）→ 压缩到 **14,452 B**：合并重复条目（showDialog 两处、hdc 兜底两处、
  unsigned 签名约束三处）、合并早期版本行（5.0.28–42 / 5.0.43–46）、把细节移入 skill。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.count('### 13:10 5.0.52b') == 1, '找不到 5.0.52b 小节'
s2 = s + ADD
io.open(P, 'w', encoding='utf-8', newline='').write(s2)
print('OK: 日志已追加，%d -> %d' % (len(s), len(s2)))
