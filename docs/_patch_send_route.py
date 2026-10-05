# -*- coding: utf-8 -*-
"""把 LanService.sendFiles 的硬编码 V5Transfer.send 改成按对端 dataVersion 分流。"""
import io

p = r'E:/lanshare-harmony/LANShareV5/entry/src/main/ets/service/LanService.ets'
s = io.open(p, encoding='utf-8', newline='').read()

old = """      // \u2605 v5\uff081.35\uff09\u53d1\u9001\uff1a\u5b57\u8282\u5e8f\u5217\u4e0e\u5c40\u57df\u7f51\u4e92\u4f20 1.35 \u4fee\u6539\u7248\u9010\u4f4d\u5bf9\u9f50\u3002
      // encData \u56fa\u5b9a false\uff1aAndroid \u7aef\u8bfb\u7684\u662f\u672c\u5730\u504f\u597d PreConfig.ENC_DATA\uff0c
      // \u9ed8\u8ba4\u672a\u5f00\u542f\uff1b\u9e3f\u8499\u4fa7\u8ddf\u968f\u9ed8\u8ba4\u503c\u4ee5\u4fdd\u8bc1\u4e92\u901a\u3002
      return await V5Transfer.send(this.self, dev, files, false,
        (r: TransferReport) => this.onTransferReport(r));"""

new = """      // \u2605 \u51fa\u7ad9\u534f\u8bae\u5206\u6d41\uff1a\u6309**\u5bf9\u7aef\u5e7f\u64ad\u7684** dataVersion \u9009\u534f\u8bae\u6808\u3002
      //   - >= 5\uff081.35 \u4fee\u6539\u7248 / \u672c\u673a LANShareV5\uff09 \u2192 v5 \u4e8c\u8fdb\u5236\u5e27\uff081101 / 1110\uff09
      //   - <= 4\uff08\u5b98\u65b9 1.2.x \u53ca\u66f4\u65e9\uff0c\u6e90\u7801 LVersion \u53ea\u5230 v4\uff09 \u2192 v4 \u88f8\u5e8f\u5217\u5316
      // \u5b98\u65b9 handleVersion \u5bf9\u300ccmd \u4e0d\u662f -2 \u4e14 dataVersion>=4\u300d\u7684\u5305\u53ea\u4f1a\u56de
      // \u300c\u4e0d\u652f\u6301\u7684\u7248\u672c\u300d\u5e76\u4e22\u5f03 \u2014\u2014 \u7ed9\u5b98\u65b9\u53d1 v5 \u5e27\u5fc5\u7136\u5931\u8d25\uff0c\u5fc5\u987b\u5206\u6d41\u3002
      // encData \u56fa\u5b9a false\uff1aAndroid \u7aef\u8bfb\u7684\u662f\u672c\u5730\u504f\u597d PreConfig.ENC_DATA\uff0c
      // \u9ed8\u8ba4\u672a\u5f00\u542f\uff1b\u9e3f\u8499\u4fa7\u8ddf\u968f\u9ed8\u8ba4\u503c\u4ee5\u4fdd\u8bc1\u4e92\u901a\u3002
      const peerVer: number = dev.dataVersion ?? 0;
      if (peerVer >= LanConfig.V5_MIN_DATA_VERSION) {
        this.pushLog(`\u51fa\u7ad9\u534f\u8bae\uff1av5\uff08\u5bf9\u7aef dataVersion=${peerVer}\uff09`);
        this.emit();
        return await V5Transfer.send(this.self, dev, files, false,
          (r: TransferReport) => this.onTransferReport(r));
      }
      this.pushLog(`\u51fa\u7ad9\u534f\u8bae\uff1av4\uff08\u5bf9\u7aef dataVersion=${peerVer}\uff09`);
      this.emit();
      return await FileTransfer.send(this.self, dev, files, false,
        (r: TransferReport) => this.onTransferReport(r));"""

n = s.count(old)
if n != 1:
    raise SystemExit('anchor count = %d (expect 1)' % n)

s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched sendFiles: ok')
