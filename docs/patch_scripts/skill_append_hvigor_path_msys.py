# -*- coding: utf-8 -*-
"""
给 skill `harmonyos-hvigor-cli-build` 追加一节：
「Git Bash 里 PATH 被 MSYS 转坏 → spawn java ENOENT（JAVA_HOME 明明是对的）」
（2026-10-02 实测：5.0.53 构建时连撞两次）

幂等：哨兵判重。写文件保持 LF。
"""
import io, sys

P = r'C:\Users\vivi\.workbuddy\skills\harmonyos-hvigor-cli-build\SKILL.md'
SENTINEL = '## ⚠️ Git Bash 里 PATH 被 MSYS 转坏'

ADD = '''

## ⚠️ Git Bash 里 PATH 被 MSYS 转坏 → `spawn java ENOENT`（JAVA_HOME 明明是对的）

### 症状

`JAVA_HOME` 已设、`$JAVA_HOME/bin/java.exe` 确实存在、`CompileArkTS` 也已经过了，
但 `PackageHap` 这一步报：

```
> hvigor ERROR: Failed :entry:default@PackageHap...
> hvigor ERROR: Error Code: 00308018 Unknown Error
spawn java ENOENT
```

`00308018` + `spawn java ENOENT` 的常规解释是「没装 JDK」，
但**在 Git Bash 下还有第二种成因**：JDK 装得好好的，是 **PATH 被 MSYS 转坏了**。

### 根因：MSYS 把 PATH 里的 `C:` 当成了 POSIX 路径分隔符

在 Git Bash 里这样设 PATH 是**坏的**：

```bash
export PATH="C:/Users/me/node:$JAVA_HOME/bin:$PATH"
#                  ↑ 这个 "C:" 会被 MSYS 当成 POSIX 的 ":" 分隔符
```

实测 `node -e "console.log(process.env.PATH)"` 拿到的是：

```
"C;C:\\Users\\vivi\\.workbuddy\\binaries\\PortableGit\\versions\\1.2.0\\Users\\vivi\\...\\node;..."
 #↑ 每个 "C:/xxx" 被拆成 "C" 与 "/xxx"；前半段 "C" 又被当相对路径展开成了 Git 安装目录
```

Windows 拿到这种 PATH **根本解析不出 java** ⇒ `spawn java` 直接 ENOENT，
而 hvigor 把一切包装成「Error Code: 00308018」，看起来像 JDK 没装。

⚠️ 若当前 shell 预设了 `MSYS_NO_PATHCONV=1` / `MSYS2_ARG_CONV_EXCL=*`
（很多 agent / 沙箱环境会设），**连正确的 `/c/Users/...` 也不会被转换**，
会以字面量 `C:\\c\\Users\\...` 传下去 —— 症状完全一样。

### 修法（实测有效）

```bash
unset MSYS_NO_PATHCONV MSYS2_ARG_CONV_EXCL          # ① 先放开路径转换
NP=/c/Users/vivi/.workbuddy/binaries/node/versions/22.22.2-3
JH=/c/Users/vivi/.workbuddy/binaries/java/jdk-21.0.2
export PATH="$NP:$JH/bin:$PATH"                      # ② 用纯 MSYS 路径 + 冒号分隔
export DEVECO_SDK_HOME="D:/Downloads/.../command-line-tools/sdk"
export JAVA_HOME="C:/Users/vivi/.workbuddy/binaries/java/jdk-21.0.2"   # 不进 PATH，C:/ 风格无妨
"$NP/node.exe" "D:/Downloads/.../command-line-tools/hvigor/bin/hvigorw.js" \\
    assembleHap --mode module -p product=default
```

**判据口诀** —— 设完 PATH 先跑这一句，一眼看出有没有被转坏：

```bash
"$NP/node.exe" -e "console.log(process.env.PATH.split(';').filter(s=>/java/i.test(s)))"
```

- 打印 `C:\\Users\\vivi\\...\\jdk-21.0.2\\bin`（反斜杠 + 分号分隔）→ **对**
- 打印 `C;C:\\Users\\vivi\\...\\PortableGit\\...\\Users\\vivi\\...` → **PATH 被 MSYS 转坏了**，按上面重设

### 两个容易被误判的点

1. **`env PATH="C:/a;C:/b" node.exe` 这种「显式分号」写法也不行** ——
   MSYS 对 PATH 这个**特殊变量**照样做转换，`C:` 还是会被拆。
   必须走「`unset` + MSYS 风格路径」。
2. **`spawn java ENOENT` 不要只往「装 JDK」方向查** ——
   先确认 `java.exe` 存在（`ls "$JAVA_HOME/bin/java.exe"`），存在就一定是 PATH 问题。
'''

s = io.open(P, encoding='utf-8', newline='').read()
if SENTINEL in s:
    print('ALREADY APPLIED'); sys.exit(0)
assert s.endswith('\n'), '文件末尾不是换行'
assert s.count('## 无 IDE 时怎么批量改源码') == 1, '找不到定位锚点'
s2 = s + ADD
io.open(P, 'w', encoding='utf-8', newline='\n').write(s2)
print('OK: 已追加，%d -> %d' % (len(s), len(s2)))
