"""
协议字节级对拍驱动

流程：
  1. 用 Node 执行 check.mjs —— 它会把**真实的 .ets 交付文件**降级为可执行 JS，
     跑出一组用例的十六进制输出
  2. 用 ref.py —— Java 源码的逐行 Python 转写 —— 算同一组用例
  3. 逐字节比对

退出码：0 全部一致；1 存在差异；2 降级器/环境故障

判读方式：
  - 「Java 参考」列 = Android 端现网行为
  - 「.ets 实测」列 = HarmonyOS 端交付物行为
  - 两列相同 => 协议零漂移，鸿蒙端可与 Android/Windows 端直接互通
"""
import json
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ref import DataEnc, DataDec, udp_unwrap, MAGIC_NUM  # noqa: E402


# ------------------------------------------------------------------ 参考用例

def hexx(b):
    return ''.join('%02x' % x for x in b)


def ref_cases():
    out = []

    # 1. 空 body 的 UDP 探测包
    e = DataEnc(0)
    e.pack_data(1001)
    out.append(('udpEmpty(UDP_GET_DEVICES)', hexx(e.enc_data_udp())))

    # 2. UDP 心跳包
    e = DataEnc(64)
    e.pack_data(1002)
    e.put_string('我的小米手机-中文')
    out.append(('udpString(UDP_SET_DEVICES, 中文设备名)', hexx(e.enc_data_udp())))

    # 3. 多字段混合
    e = DataEnc(128)
    e.pack_data(1105)
    e.set_count(7)
    e.put_byte(0x41)
    e.put_bool(True)
    e.put_bool(False)
    e.put_short(0xBEEF)
    e.put_int(-123456789)
    e.put_long(1735689600000)
    e.put_string('hello world')
    e.put_string('')
    e.put_bytes(bytes([0, 1, 127, 128, 254, 255]))
    out.append(('mixed fields', hexx(e.wire())))

    # 4. 全 0xFF payload（走 putBytes：4 字节长度前缀 + 数据，与 Java putBytes 一致）
    e = DataEnc(272)
    e.pack_data(3002)
    e.put_bytes(bytes([0xFF] * 256))
    out.append(('payload all 0xFF', hexx(e.wire())))

    # 5. 全 0x00 payload
    e = DataEnc(272)
    e.pack_data(3003)
    e.put_bytes(bytes([0x00] * 256))
    out.append(('payload all 0x00', hexx(e.wire())))

    # 6. 0x00..0xFF 全字节值
    e = DataEnc(272)
    e.pack_data(1101)
    e.put_bytes(bytes(range(256)))
    out.append(('payload 0x00..0xFF', hexx(e.wire())))

    # 7. 负命令码
    e = DataEnc(8)
    e.pack_data(-2)
    e.put_int(-1)
    out.append(('negative cmd (-2)', hexx(e.wire())))

    # 8. int 边界
    e = DataEnc(64)
    e.pack_data(2147483647)
    e.set_count(-2147483648)
    e.put_int(-1)
    e.put_int(0)
    e.put_int(1)
    out.append(('int boundary values', hexx(e.wire())))

    return out


def ref_round_trip():
    """参考实现的往返校验，返回失败描述列表"""
    bad = []

    e = DataEnc(64)
    e.pack_data(1002)
    e.set_count(3)
    e.put_string('设备A')
    e.put_int(42)
    udp = e.enc_data_udp()

    d = udp_unwrap(udp)
    if d is None:
        bad.append('udp_unwrap 返回 None')
    else:
        if d.get_cmd() != 1002:
            bad.append('cmd 不符: %s' % d.get_cmd())
        if d.get_count() != 3:
            bad.append('count 不符: %s' % d.get_count())
        if d.get_string() != '设备A':
            bad.append('string 不符')
        if d.get_int() != 42:
            bad.append('int 不符')

    junk = bytes(range(1, 17))
    if udp_unwrap(junk) is not None:
        bad.append('垃圾包未被丢弃')

    return bad


# ------------------------------------------------------------------ 主流程

def main():
    ref = ref_cases()
    ref_fail = ref_round_trip()

    proc = subprocess.run(
        ['node', '--experimental-strip-types', os.path.join(HERE, 'check.mjs')],
        capture_output=True, text=True, shell=False
    )
    if proc.returncode != 0:
        print('!! Node 侧执行失败 (exit=%d)' % proc.returncode)
        print('--- stdout ---')
        print(proc.stdout)
        print('--- stderr ---')
        print(proc.stderr)
        return 2

    try:
        actual = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        print('!! 无法解析 Node 输出：')
        print(proc.stdout[:4000])
        print(proc.stderr[:2000])
        return 2

    act_map = {c['name']: c['hex'] for c in actual['cases']}

    print('=' * 78)
    print('LanShare 协议字节级对拍：Android(Java 参考) vs HarmonyOS(.ets 实测)')
    print('=' * 78)
    print('魔数  : 0x%08X (Java) / 0x%08X (.ets)' % (MAGIC_NUM, actual.get('magic', -1)))
    print('-' * 78)

    mismatches = 0
    for name, rhex in ref:
        ahex = act_map.get(name)
        if ahex is None:
            print('[缺失] %s' % name)
            mismatches += 1
            continue
        if rhex == ahex:
            n = len(rhex) // 2
            print('[一致] %-42s %3d bytes' % (name, n))
        else:
            mismatches += 1
            print('[不一致] %s' % name)
            print('   Java 参考: %s' % rhex)
            print('   .ets 实测: %s' % ahex)
            # 定位首个差异字节
            for i in range(0, min(len(rhex), len(ahex)), 2):
                if rhex[i:i + 2] != ahex[i:i + 2]:
                    print('   首个差异 @ byte %d: java=0x%s ets=0x%s'
                          % (i // 2, rhex[i:i + 2], ahex[i:i + 2]))
                    break
            if len(rhex) != len(ahex):
                print('   长度差异: java=%d bytes, ets=%d bytes'
                      % (len(rhex) // 2, len(ahex) // 2))

    print('-' * 78)
    rt = actual.get('roundTripFailures', [])
    if ref_fail or rt:
        print('往返自洽校验:')
        for x in ref_fail:
            print('  [Java 参考] %s' % x)
        for x in rt:
            print('  [.ets 实测] %s' % x)
        mismatches += len(ref_fail) + len(rt)
    else:
        print('往返自洽校验: Java 参考 / .ets 实测 均通过')

    print('=' * 78)
    if mismatches == 0:
        print('结论: 通过。协议与 Android 端位级一致，可直接互通。')
        return 0
    print('结论: 失败，存在 %d 处差异。' % mismatches)
    return 1


if __name__ == '__main__':
    sys.exit(main())
