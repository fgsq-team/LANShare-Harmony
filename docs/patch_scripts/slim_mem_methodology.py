# -*- coding: utf-8 -*-
"""
精简 MEMORY.md：把「方法论」节的**实录细节**折叠，只留结论指针
（全文已在 skill `harmonyos-arkui-ui-pitfalls` 第 36 节）。

【为什么这次能压】
上轮压 UI 节时，5.1.1~5.1.12 又把十二条判据写回 MEMORY，
而那批判据的**抽象结论**现已全部收进 skill 第 36 节（六条通用纪律 + 四个附条）。
MEMORY 里留着的是**实录**（版本号、行号、逐步推理）——
这些查 `git log`（每版 1 commit + tag）与 `docs/backups/` 更快更准。

【压的原则（沿用前两轮）】
留：可执行的判据 + 判据的名字（便于日后 grep 记忆找到 skill 对应节）
删：推理过程、版本号罗列、具体行号、对话原文
"""
import io
import sys
import os

MEM = r'E:\lanshare项目\.workbuddy\memory\MEMORY.md'
BAK = r'E:\lanshare项目\.workbuddy\_memory_snapshot_2026102'

s0 = io.open(MEM, encoding='utf-8').read()
if '四条通用判据' in s0:
    print('ALREADY')
    sys.exit(0)

os.makedirs(BAK, exist_ok=True)
io.open(os.path.join(BAK, 'MEMORY.md.v5112slim'), 'w', encoding='utf-8', newline='\n').write(s0)
print('备份完成（%d chars）' % len(s0))

i = s0.find('\n## 方法论')
j = s0.find('\n## ', i + 5)
assert i > 0 and j > i, (i, j)
old_sec = s0[i:j]
print('原方法论节 %d chars' % len(old_sec))

NEW = '''
## 方法论（跨版本通用）
**5.1.x 连续十二版的判据已抽象成 skill `harmonyos-arkui-ui-pitfalls` **第 36 节**「判据的六条通用纪律」+ 四个附条。改代码前先翻那一节；下面只留索引与本项目特有的几条。**

1. **协议兼容**：新增字段按对端广播版本号分流。本机绿但对端失败 → **别改本机判定**（掩盖症状），查**发送流漏了哪个对端必需帧**。
2. ★ **「1 个不触发、多个才触发」= 时序依赖** → 队列 + 已处理集合 + 每次刷新都重试。★ **「只有重启才现形」= 持久化格式不对称**（Map 落盘必须连 key 一起写；`cacheDir` 会被清 → 放 `filesDir`）。
3. ★ **防失败改动本身可能引入新 bug**。定不出真因就做看门狗。**跨调用边界的隐式状态**（如换引用闸门）尤其要防。
4. ★★ **记账粒度必须跟「最细的可独立变化的单位」对齐**：一批 N 张图 = 一条消息 ⇒ 整批共用记账，删一张 = 整批失效；**首选在「生成消息」那步就拆**。下标必须来自消息本身；按名反查遇同名是多对一，必须**时间就近**消歧。
5. ★★★ **「改了但没好」连着两轮 ⇒ 停止猜测，改用观测**。**排除法只能证伪，不能证成**。做法：出**纯诊断版**（不改行为，只在关键节点打一行日志）。⚠️ 诊断日志只打**低频路径**，绝不放在渲染路径。
6. ★★ **「界面又刷一遍」= 显示身份绑在了会消失的东西上**（详见 skill 第 30~35 节）。
7. ★ `hdc` 无设备时交付不停（夸克网盘），但必须给「装完测什么、看哪几行日志」的**可自验清单**。
8. ★ **发版体检**：`ABOUT_FALLBACK_VER` 每次发版要同步（5.0.29 踩过「关于页显示旧版」）。

### 本项目特有的判据（skill 第 36 节给的是通用形态，这里只记差异）
- **同形不同义的状态要新开一套**（5.1.2）：`albumMap`（相册）与 `localMap`（本地文件）key 形态与 value 语义都不同 ⇒ 照抄成熟套路**一比一对应**六项（内存 Map / preferences key / 落盘 / 加载 / 查询 / 写点）并贴对应表；**加载要与老的那次合并**（同一次 `preferences` 会话）。
- **拆消息与聚合成宫格是两个独立开关**（5.1.4）：`appendFileChat` 控消息条数，`batchId`+`groupAllMedia` 控渲染形式。⚠️ **给非媒体共 `batchId` 会让界面看起来完全没变**（`allMedia` 对 zip 判 false ⇒ 不走宫格）。
- **自绘弹窗必须逐个登记到 `onBackPress`**（5.1.4）：漏一个 = 按返回就退出应用，而弹窗还开着。症状很好认。
- **判据的通用形态在 skill 第 36 节**：① 事实 vs 路径派生判断（路径可能为空）② 覆盖所有输入类别 ③ 同一状态在不同代码路的语义前提分别声明 ④ 表达式承载的显示必须真的重建（要 `@State` tick，**两条缺一不可**）⑤ 提示 vs 取证要分清 ⑥ 多条入口每条都记账。附：ArkTS 注释里不能有 `*/`；`Text` 没有 `.align()`；标记文件会不会被自己重写；「连错两轮」时别在同一层继续修。
'''

s = s0[:i] + NEW + s0[j:]

# ---------------- 不变量 ----------------
# 判据的名字要保留（便于日后 grep 找到 skill 对应处）
for k in ('记账粒度', '防失败改动', '停止猜测', '同形不同义', '两个独立开关',
          'onBackPress', '事实 vs 路径派生', '多条入口每条都记账',
          '注释里不能有', '标记文件', '连错两轮', '表达式承载'):
    assert k in s, '判据名被误删: %s' % k
# skill 指针在
assert '第 36 节' in s
# 其它节未破坏
for keep in ('## 工程与环境', '## 构建与推送', '## 源码批量补丁', '## 真机验证',
             '## 保存路径', '## V5 协议要点', '## UI 约定', '## ★ ArkTS Promise',
             '## 未结项', '## 已完成', '## ★★★ 四条结构性铁律'):
    assert keep in s, '节丢失: %s' % keep
# 未结项里的当前版本已更新
assert 'v5.1.3' in s or 'v5.1.12' in s

io.open(MEM, 'w', encoding='utf-8', newline='\n').write(s)
print('OK  MEMORY.md %d -> %d  (省 %d)' % (len(s0), len(s), len(s0) - len(s)))
