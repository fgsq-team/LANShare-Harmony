# -*- coding: utf-8 -*-
"""把 sendParallel 里那段写乱的进度换算替换成干净实现（按行号区间定位）。"""
import io

P = r'E:\lanshare-harmony\LANShareV5\entry\src\main\ets\service\V5Transfer.ets'
s = io.open(P, encoding='utf-8').read()
lines = s.split('\n')

# 定位区间：从「// ★ 5.1.15：车道 k 的进度」到「tasks.push(V5Transfer.sendPlain」
start = None
end = None
for i, l in enumerate(lines):
    if '5.1.15：车道 k 的进度' in l:
        start = i
    if start is not None and 'tasks.push(V5Transfer.sendPlain(self, target, lanes[i], encData, wrapped));' in l:
        end = i
        break
assert start is not None and end is not None, (start, end)
# 区间必须完整包住整个语法块
probe = '\n'.join(lines[start:end + 1])
for k in ('laneIdx', 'laneCount', 'before', 'globalIdx', 'grandBytes', 'wrapped', 'void before;'):
    assert k in probe, '区间不完整，缺 %s' % k

NEW = '''      // ★ 5.1.15：车道 k 的进度**换算成全局坐标**再上报。
      //   否则两条车道都从 `0/1, 0%` 起算 ⇒ UI 进度来回跳；
      //   且上层 `lastReportBytes` 的增量统计会被另一条车道覆盖（流量统计失真）。
      //
      //   轮转规则：全局项序 =「本车道内 0-based 序」× 车道数 + 车道号。
      //   例：2 车道、4 项 ⇒ A=[1,3]（全局 1,3）、B=[2,4]（全局 2,4）。
      const laneIdx: number = i;
      const laneCount: number = n;
      const grandBytes: number = V5Transfer.sumSize(files);
      // 本车道之前的车道已发出的字节数（作为本车道进度的起点）
      const laneStartBytes: number = V5Transfer.sumSize(lanes.slice(0, laneIdx).flat());
      const wrapped: TransferCallback = (r: TransferReport): void => {
        const j: number = Math.max(0, r.fileIndex - 1);         // 本车道内 0-based
        const globalIdx: number = j * laneCount + laneIdx + 1;  // 全局项序（1-based）
        const cur: number = laneStartBytes + r.bytes;
        onReport({
          ...r,
          fileIndex: globalIdx,
          fileCount: files.length,
          bytes: r.done ? grandBytes : cur,
          percent: grandBytes > 0 ? Math.floor(cur * 100 / grandBytes) : r.percent
        });
      };
      tasks.push(V5Transfer.sendPlain(self, target, lanes[i], encData, wrapped));'''

out = '\n'.join(lines[:start]) + '\n' + NEW + '\n' + '\n'.join(lines[end + 1:])
assert '\r\n' not in out
assert '�' not in NEW
io.open(P, 'w', encoding='utf-8', newline='\n').write(out)

# 回读校验
chk = io.open(P, encoding='utf-8').read()
for k in ('5.1.15：车道 k 的进度', 'laneStartBytes', 'globalIdx', 'wrapped'):
    assert k in chk, '回读缺 %s' % k
assert 'void before;' not in chk, '残留 before'
assert 'const before' not in chk, '残留 const before'
print('OK  替换区间 %d-%d 行，文件 %d chars' % (start + 1, end + 1, len(chk)))
