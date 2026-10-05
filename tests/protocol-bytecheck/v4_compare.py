"""
v4 协议字节级对拍驱动

流程：
  1. 用 Node 执行 v4_check.mjs —— 它把**真实的 .ets 交付文件**降级为可执行 JS，
     跑出实测结果，同时把「用例输入原文」一并回传
  2. 本脚本用**独立的 Python 实现**重算每个用例的期望值
  3. 逐项比对

为什么让 Node 回传用例原文：用例清单只保留一份，两侧不会各写一份而悄悄漂移。

比对口径：
  - JSON 解析       → **语义深比较**（不是字符串比较）
                      JS 里所有数字都是 double，'1e3' 在 JS 是 1000、在 Python 是 1000.0，
                      拿字符串比会误报；所以按数值比。
  - JSON 生成(quote) → **字符串严格比较**（这里比的正是转义格式）
  - FileCrypto      → 十六进制严格比较
  - ProtoIO         → 十六进制严格比较

退出码：0 全部一致；1 存在差异；2 环境故障
"""
import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NODE = os.environ.get(
    'NODE_BIN',
    r'C:\Users\vivi\.workbuddy\binaries\node\versions\22.22.2-3\node.exe',
)


# ══════════════════════════════════════════════════════════════
# 独立参考实现（源自 Java 源码，非从 .ets 转写）
# ══════════════════════════════════════════════════════════════

def ref_enc(data: bytes, index: int) -> bytes:
    """mUtil.encData: out = ((b - 1) & 0xFF) ^ ((index + j) & 0xFF)"""
    return bytes((((b - 1) & 0xFF) ^ ((index + j) & 0xFF)) & 0xFF
                 for j, b in enumerate(data))


def ref_dec(data: bytes, index: int) -> bytes:
    """mUtil.decData: out = ((b ^ ((index + j) & 0xFF)) + 1) & 0xFF"""
    return bytes(((b ^ ((index + j) & 0xFF)) + 1) & 0xFF
                 for j, b in enumerate(data))


def ref_int(v: int) -> bytes:
    """CustomDataOutputStream.writeInt —— 4 字节大端有符号"""
    return struct.pack('>i', v)


def ref_long(v: int) -> bytes:
    """CustomDataOutputStream.writeLong —— 8 字节大端有符号"""
    return struct.pack('>q', v)


def ref_bool(v: bool) -> bytes:
    return b'\x01' if v else b'\x00'


def ref_byte(v: int) -> bytes:
    return bytes([v & 0xFF])


def ref_str(s):
    """CustomDataOutputStream.writeString —— null 写 -1；否则 4 字节长度 + UTF-8"""
    if s is None:
        return ref_int(-1)
    body = s.encode('utf-8')
    return ref_int(len(body)) + body


def hexx(b: bytes) -> str:
    return b.hex()


# ══════════════════════════════════════════════════════════════
# 语义深比较（数字按值比，bool 不与 int 混同）
# ══════════════════════════════════════════════════════════════

def deep_eq(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(deep_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a.keys()) == set(b.keys()) and all(deep_eq(a[k], b[k]) for k in a)
    return False


# ══════════════════════════════════════════════════════════════
# 期望值构建
# ══════════════════════════════════════════════════════════════

class Expect:
    """一项期望：kind = 'hex' | 'str' | 'json' | 'status'"""
    __slots__ = ('key', 'kind', 'value')

    def __init__(self, key, kind, value):
        self.key = key
        self.kind = kind
        self.value = value


def build_expectations(node: dict):
    exp = []

    # ---------------- JSON 解析 ----------------
    for i, src in enumerate(node['jsonCases']):
        try:
            exp.append(Expect(f'json:{i}', 'json', json.loads(src)))
        except Exception:
            exp.append(Expect(f'json:{i}', 'status', 'PARSE_ERROR'))

    for name, src in node['jsonBad']:
        try:
            json.loads(src)
            exp.append(Expect(f'jsonbad:{name}', 'status', 'WRONGLY_OK'))
        except Exception:
            exp.append(Expect(f'jsonbad:{name}', 'status', 'FAIL_OK'))

    for name, src, expected in node['jsonGuard']:
        exp.append(Expect(f'jsonguard:{name}', 'status', expected))

    # ---------------- JSON 生成 ----------------
    for i, s in enumerate(node['quoteCases']):
        # Python 的 json.dumps(ensure_ascii=False) 与实现的转义集合一致：
        # " \ \b \f \n \r \t + 其余 <0x20 走 \uXXXX，非 ASCII 原样输出，'/' 不转义
        exp.append(Expect(f'quote:{i}', 'str',
                          json.dumps(s, ensure_ascii=False)))

    # ---------------- FileCrypto ----------------
    sample = bytes.fromhex(node['fileCrypto']['sampleHex'])
    for idx in node['fileCrypto']['indices']:
        exp.append(Expect(f'enc:{idx}', 'hex', hexx(ref_enc(sample, idx))))
        exp.append(Expect(f'decRound:{idx}', 'status', 'OK'))
    exp.append(Expect('filecrypto:roundtrip256', 'status', 'OK'))
    exp.append(Expect('filecrypto:chunked-equals-whole', 'status', 'OK'))
    exp.append(Expect('filecrypto:off-len-clamped', 'hex',
                      hexx(ref_enc(sample[250:300], 250))))

    # ---------------- ProtoIO ----------------
    for v in node['proto']['ints']:
        exp.append(Expect(f'proto:int:{v}', 'hex', hexx(ref_int(v))))
        exp.append(Expect(f'proto:beInt:{v}', 'str', str(v)))
    for v in node['proto']['longs']:
        exp.append(Expect(f'proto:long:{v}', 'hex', hexx(ref_long(v))))
    for s in node['proto']['strings']:
        exp.append(Expect(f'proto:str:{s}', 'hex', hexx(ref_str(s))))
    exp.append(Expect('proto:str:null', 'hex', hexx(ref_str(None))))
    exp.append(Expect('proto:bool:true', 'hex', hexx(ref_bool(True))))
    exp.append(Expect('proto:bool:false', 'hex', hexx(ref_bool(False))))
    exp.append(Expect('proto:byte:0x8f', 'hex', hexx(ref_byte(0x8F))))

    joined = (ref_int(-2) + ref_str('dev') + ref_int(1101)
              + ref_bool(False) + ref_str('{"files":[]}'))
    exp.append(Expect('proto:join', 'hex', hexx(joined)))

    return exp


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

GROUP_TITLE = [
    ('json:', 'MiniJson 解析（语义深比较）'),
    ('jsonbad:', 'MiniJson 必须拒绝的输入'),
    ('jsonguard:', 'MiniJson 有意分歧（深度护栏）'),
    ('quote:', 'MiniJson 生成 / 转义（字符串严格比较）'),
    ('enc:', 'FileCrypto 加密（严格十六进制比较）'),
    ('decRound:', 'FileCrypto 解密还原'),
    ('filecrypto:', 'FileCrypto 结构与边界'),
    ('proto:', 'ProtoIO 裸序列化（严格十六进制比较）'),
]


def group_of(key: str) -> str:
    best = '其他'
    best_len = -1
    for pre, title in GROUP_TITLE:
        if key.startswith(pre) and len(pre) > best_len:
            best, best_len = title, len(pre)
    return best


def show(v, kind, limit=200):
    if kind == 'hex':
        s = str(v)
        return s if len(s) <= limit else f'{s[:limit]}…（共 {len(s) // 2} 字节）'
    if kind == 'json':
        s = json.dumps(v, ensure_ascii=False, sort_keys=True)
        return s if len(s) <= limit else f'{s[:limit]}…'
    s = str(v)
    return s if len(s) <= limit else f'{s[:limit]}…'


def main():
    script = os.path.join(HERE, 'v4_check.mjs')
    cmd = [NODE, '--experimental-strip-types', script]
    if not os.path.isfile(NODE):
        cmd = ['node', '--experimental-strip-types', script]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if proc.returncode != 0:
        print(f'!! Node 侧执行失败 (exit={proc.returncode})')
        print('--- stdout ---\n' + (proc.stdout or '')[:4000])
        print('--- stderr ---\n' + (proc.stderr or '')[:4000])
        return 2

    try:
        node = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        print('!! 无法解析 Node 输出：')
        print((proc.stdout or '')[:4000])
        print((proc.stderr or '')[:2000])
        return 2

    actual = node['results']
    expectations = build_expectations(node)
    # 按分组归拢（稳定排序，组内保持原顺序），否则 enc:/decRound: 交替会让表头反复出现
    order = {t: i for i, (_p, t) in enumerate(GROUP_TITLE)}
    expectations.sort(key=lambda e: order.get(group_of(e.key), 99))

    print('=' * 82)
    print('LANShare v4 协议字节级对拍：Java/Python 参考  vs  HarmonyOS .ets 实测')
    print('=' * 82)

    mismatches = 0
    missing = 0
    current_group = None
    ok_count = 0

    for e in expectations:
        g = group_of(e.key)
        if g != current_group:
            current_group = g
            print('-' * 82)
            print(f'【{g}】')
        if e.key not in actual:
            print(f'  [缺失] {e.key}')
            missing += 1
            continue
        got = actual[e.key]
        if e.kind == 'json':
            try:
                got_obj = json.loads(got)
            except Exception:
                print(f'  [不一致] {e.key}')
                print(f'       实测无法作为 JSON 解析: {str(got)[:160]}')
                mismatches += 1
                continue
            same = deep_eq(e.value, got_obj)
        else:
            same = (str(e.value) == str(got))

        if same:
            ok_count += 1
            if e.kind in ('hex',):
                print(f'  [一致] {e.key:<34} {len(str(got)) // 2:>6} bytes')
            else:
                print(f'  [一致] {e.key:<34} {show(got, e.kind, 90)}')
        else:
            mismatches += 1
            print(f'  [不一致] {e.key}')
            print(f'       参考: {show(e.value, e.kind)}')
            print(f'       实测: {show(got, e.kind)}')
            if e.kind == 'hex':
                a, b = str(e.value), str(got)
                for i in range(0, min(len(a), len(b)), 2):
                    if a[i:i + 2] != b[i:i + 2]:
                        print(f'       首个差异 @ byte {i // 2}: 参考=0x{a[i:i+2]} 实测=0x{b[i:i+2]}')
                        break
                if len(a) != len(b):
                    print(f'       长度差异: 参考={len(a)//2}B 实测={len(b)//2}B')

    print('-' * 82)
    extra = sorted(set(actual) - {e.key for e in expectations})
    if extra:
        print(f'注: 实测多出 {len(extra)} 项未被参考覆盖: {extra[:6]}')

    print('=' * 82)
    print(f'合计 {len(expectations)} 项：一致 {ok_count}，不一致 {mismatches}，缺失 {missing}')
    if mismatches == 0 and missing == 0:
        print('结论: 通过。MiniJson / FileCrypto / ProtoIO 与参考实现位级一致。')
        return 0
    print(f'结论: 失败，存在 {mismatches + missing} 处问题。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
