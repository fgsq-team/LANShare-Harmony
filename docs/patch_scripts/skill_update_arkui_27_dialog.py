# -*- coding: utf-8 -*-
"""
更新 skill `harmonyos-arkui-ui-pitfalls` 第二十七节：
补上 5.0.54 确诊的两条硬结论 ——
  ① `showAssetsCreationDialog` 会**永不 settle**（必须自己套超时）
  ② `title` **不能带 `.`**，且返回数量与提交不符时**绝不能按位置配对**（会写错内容 + 误删原图）

幂等：哨兵判重。写文件保持 LF。
"""
import io, sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-arkui-ui-pitfalls\SKILL.md'
SENTINEL = '### 三个必须自己兜住的坑（5.0.54 真机确诊）'

ADD = '''

### 三个必须自己兜住的坑（5.0.54 真机确诊）

上面的「写授权」只是**读**的问题，下面三条是**调用契约**本身的问题，每条都造成过真机事故。

#### ① `title` 里**不能有 `.`** —— 它是「不含后缀的文件名」

`PhotoCreationConfig.title` 的语义是「不含文件后缀的标题」。**带点的 title 会让系统建不出资产**，
而且**不报错**，只是**少返回几个 URI**。

真机证据（一次提交 4 张，只回来 2 个 URI）：

| 提交顺序 | 文件名 | 旧代码算出的 title | 结果 |
|---|---|---|---|
| [0] | `screenshot_20261001_234405_com.fgsqw.lanshare.jpg` | `screenshot_..._com.fgsqw.lanshare` ← **带点** | **挂** |
| [1] | `IMG_20260929_201626.jpg` | `IMG_20260929_201626` | 成功 |
| [2] | `扫描全能王 2026-09-22 22.33.jpg` | `扫描全能王 2026-09-22 22.33` ← **带点** | **挂** |
| [3] | `IMG_20260907_092804.jpg` | `IMG_20260907_092804` | 成功 |

> 4 个里挂的恰好是两个带点的 —— 与「4 张只成功 2 张」**逐个对上**。
> ⚠️ 旧实现的非法字符表 `\\/:*?"'`<>|{}[]` **漏了点号**，只看官方文档也不会发现。

```ts
// ✅ 把 `.` 一并换掉
const bad: string = '\\\\/:*?"\\'`<>|{}[].';
```

另外要**给同一批的 title 去重**（第 2 个起追加 `_2`）—— 同名同后缀同样会少建资产。

#### ② 返回数量 ≠ 提交数量时，**绝对不能按位置配对**

上面那张表里，返回的 2 个 URI 是**为 [1] 和 [3] 创建的**。旧代码

```ts
const n = Math.min(uris.length, paths.length);
for (let i = 0; i < n; i++) { copyTo(paths[i], uris[i]); }   // ❌ 位置硬配
```

把 `paths[0]`(screenshot) 的字节写进了 `uris[0]`(实为 [1] 的资产)、`paths[1]` 写进 `uris[1]`(实为 [3] 的)
⇒ **相册里两张内容全错位**；更糟的是它把 `paths[0]`、`paths[1]` 当成「保存成功」
**删掉了沙箱里的原文件** ⇒ **原图直接丢失**。

**正确做法**：数量不符就**什么都不写、什么都不删**，翻成「**逐张提交**」重试 ——
每次只传 1 个，返回只可能是 0 或 1，**结构上就没有歧义**。

```ts
if (uris.length !== paths.length) {
  log(`返回 ${uris.length} ≠ 提交 ${paths.length}，无法确定对应关系`);
  log(`  返回 URI[0]：${baseName(uris[0])}`);   // 打出来，便于事后核对
  this.singleShot = true;      // 下一轮逐张提交
  return;                      // ⚠️ 不写、不删
}
```

推论（可迁移）：**凡是「批量提交 ⇒ 部分返回」的接口，都不许用位置下标去对答案**，
除非契约明确保证「返回数组与提交数组一一对应且等长」。要么逐条提交，要么要求接口回带标识。

#### ③ `showAssetsCreationDialog` 会**永不 settle** —— 必须自己套超时

真机日志：提交后**连一句返回日志都没有**，闸门一直关着 **108 秒**
（只靠 45 秒看门狗 + 用户恰好把应用切后台再切回来触发刷新才恢复）；
这期间新收到的 3 张图**一次弹窗都没有**。

⚠️ 更坑的是：**超时不能当成「用户取消」**。取消要结案，超时要**留队重试**。

```ts
private static awaitDialog(helper, srcUris, cfgs): Promise<string[]> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) { settled = true; reject(new Error('超时未返回')); }
    }, 20000);
    helper.showAssetsCreationDialog(srcUris, cfgs).then((u) => {
      if (settled) { return; } settled = true; clearTimeout(timer); resolve(u);
    }).catch((e) => {
      if (settled) { return; } settled = true; clearTimeout(timer); reject(e as Error);
    });
  });
}
```

配套三条（缺一条就还是会「静默卡死」）：

1. **自驱重试**：`flushAutoSave` 通常只由「消息变化 / 列表刷新」触发。
   弹窗超时后没有新消息，就再也没人来救命了 ⇒ 超时分支自己 `setTimeout(…, 3000)` 再调一次。
2. **连续失败上限**：连续 3 次无响应就停掉自动重试，**明确告知用户可长按手动存**
   （别让它变成永久的静默失败）。
3. **看门狗放宽而不是收紧**：超时机制接管后，看门狗只兜「超时本身也没生效」，
   设成 60 秒。设太小（如 45 秒）会在**正常的长拷贝**中途复位闸门 ⇒ 同一批弹第二遍。

### 排查口诀（相册相关）

- 「提交 N 个只成功 M 个」→ 先查 **title 有没有点号 / 批内有没有重名**。
- 「相册里的图和文件名对不上」→ 查是不是**按位置硬配**了不等长的返回数组。
- 「文件凭空少了」→ 查配对失败时是不是**把没存成功的源文件也删了**。
- 「弹窗一直不出现」→ 查闸门是不是被一个**永不返回的 Promise** 钉住了（看有没有 `超时` 兜底）。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
anchor = '### 设计原则（可迁移）'
assert s.count(anchor) == 1, '锚点命中 %d 次' % s.count(anchor)
s2 = s.replace(anchor, ADD.lstrip('\n') + '\n' + anchor)
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 二十七节已扩容，%d -> %d' % (len(s), len(s2)))
