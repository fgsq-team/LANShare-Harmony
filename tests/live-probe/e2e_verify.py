#!/usr/bin/env python3
"""
网页上传/下载的端到端字节级校验。

## 为什么要这个
「接口返回 200」不等于「文件传对了」。上传路径上有一整套变换：
multipart 分帧 → 流式解析 → 去重命名 → 落盘，其中任何一环错位，
用户拿到的都是坏文件，而接口依然笑眯眯地回 200。

所以这里做闭环：把一个已知内容的文件传上去，再从手机的
`/file/<name>?path=<路径>` 读回来，**逐字节比对 sha256**。
读回来这一趟本身就顺带验证了目录列举和下载路由。

用法：python e2e_verify.py [ip] [port]
"""
import hashlib
import http.client
import json
import os
import random
import sys
import urllib.parse

HOST = sys.argv[1] if len(sys.argv) > 1 else '192.168.10.146'
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5856
BOUND = '----WebKitFormBoundaryE2Everify0001'

passed = 0
failed = 0


def check(name, ok, detail=''):
    global passed, failed
    if ok:
        passed += 1
        print('[通过] %s' % name)
    else:
        failed += 1
        print('[失败] %s   -> %s' % (name, detail))


def request(method, path, body=None, headers=None, timeout=300):
    c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    h = dict(headers or {})
    if body is not None and 'Content-Length' not in h:
        h['Content-Length'] = str(len(body))
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    status = r.status
    hdrs = dict(r.getheaders())
    c.close()
    return status, hdrs, data


def build_multipart(filename, data):
    out = []
    out.append(('--%s\r\n' % BOUND).encode('utf-8'))
    out.append(('Content-Disposition: form-data; name="file"; filename="%s"\r\n'
                % filename).encode('utf-8'))
    out.append(b'Content-Type: application/octet-stream\r\n\r\n')
    out.append(data)
    out.append(b'\r\n')
    out.append(('--%s--\r\n' % BOUND).encode('utf-8'))
    return b''.join(out)


def list_dir(path):
    body = json.dumps({'path': path}).encode('utf-8')
    st, hd, data = request('POST', '/files', body,
                           {'Content-Type': 'application/json'})
    if st != 200:
        return None, 'HTTP %d %s' % (st, data[:200])
    try:
        return json.loads(data.decode('utf-8')), ''
    except Exception as e:
        return None, 'JSON 解析失败: %s (%r)' % (e, data[:200])


def main():
    print('目标 %s:%d\n' % (HOST, PORT))

    # ---------- 1. 造一个已知文件 ----------
    random.seed(20260930)
    size = 4 * 1024 * 1024
    payload = bytes(random.getrandbits(8) for _ in range(size))
    want_sha = hashlib.sha256(payload).hexdigest()
    fname = 'e2e_check_%d.bin' % random.randint(1000, 9999)
    print('本地文件 %s  %d 字节' % (fname, size))
    print('本地 sha256 %s\n' % want_sha)

    # ---------- 2. 上传 ----------
    body = build_multipart(fname, payload)
    st, hd, data = request('POST', '/uploadFile', body, {
        'Content-Type': 'multipart/form-data; boundary=%s' % BOUND,
        'token': 'e2e',
    })
    text = data.decode('utf-8', 'replace')
    check('1 上传返回 200', st == 200, 'HTTP %d %s' % (st, text[:200]))
    print('     服务端应答: %s' % text)
    check('2 响应头带 Content-Length（浏览器才能立刻收工）',
          'Content-Length' in hd, str(hd))

    # ---------- 3. 列根目录，找到分类子目录 ----------
    root, err = list_dir('')
    if root is None:
        check('3 列出根目录', False, err)
        return
    check('3 列出根目录', True)

    # ---------- 4. 遍历所有子目录，找到刚上传的文件 ----------
    # 上传会按扩展名自动分类（.bin -> 其他/），所以不能只看第一个子目录。
    subdirs = [it.get('path', '') for it in root.get('list', []) if it.get('isDirectory')]
    print('     根目录下的分类: %s'
          % json.dumps([it.get('name') for it in root.get('list', [])][:10], ensure_ascii=False))
    entry = None
    subdir = ''
    for sd in subdirs:
        sub, _e = list_dir(sd)
        if sub is None:
            continue
        for it in sub.get('list', []):
            if it.get('name') == fname:
                entry = it
                subdir = sd
                break
        if entry:
            break
    check('4/5 在所有分类目录里找到 %s' % fname, entry is not None,
          '看了 %s，都没找到' % json.dumps(subdirs, ensure_ascii=False))
    if entry is None:
        return

    check('6 目录里的 length 与服务端落盘一致',
          entry.get('length') == size, '%s vs %s' % (entry.get('length'), size))

    # ---------- 5. 下载回来比对 ----------
    q = urllib.parse.urlencode({'path': entry.get('path', ''), 'token': 'e2e'})
    url = '/file/%s?%s' % (urllib.parse.quote(fname), q)
    st, hd, back = request('GET', url)
    check('7 下载返回 200', st == 200, 'HTTP %d %s' % (st, back[:120]))
    check('8 下载字节数一致', len(back) == size, '%d vs %d' % (len(back), size))
    got_sha = hashlib.sha256(back).hexdigest()
    check('9 下载内容 sha256 与本地上传源一致', got_sha == want_sha,
          '\n        上传前 %s\n        下载后 %s' % (want_sha, got_sha))

    # ---------- 6. 中文文件名 ----------
    cn = '端到端校验_中文名.txt'
    cn_payload = ('LANShare 端到端校验 ' * 500).encode('utf-8')
    cn_sha = hashlib.sha256(cn_payload).hexdigest()
    st, hd, data = request('POST', '/uploadFile', build_multipart(cn, cn_payload), {
        'Content-Type': 'multipart/form-data; boundary=%s' % BOUND,
        'token': 'e2e',
    })
    check('10 中文名文件上传返回 200', st == 200, 'HTTP %d %s' % (st, data[:200]))
    cn_entry = None
    for sd in subdirs:
        sub, _e = list_dir(sd)
        if sub is None:
            continue
        for it in sub.get('list', []):
            if it.get('name') == cn:
                cn_entry = it
                break
        if cn_entry:
            break
    check('11 中文文件名原样保留', cn_entry is not None,
          '看了 %s 都没找到' % json.dumps(subdirs, ensure_ascii=False))
    if cn_entry:
        q = urllib.parse.urlencode({'path': cn_entry.get('path', ''), 'token': 'e2e'})
        st, hd, back = request('GET', '/file/%s?%s' % (urllib.parse.quote(cn), q))
        ok = st == 200 and hashlib.sha256(back).hexdigest() == cn_sha
        check('12 中文名文件内容字节一致', ok,
              'HTTP %d len=%d sha=%s' % (st, len(back),
                                         hashlib.sha256(back).hexdigest()[:16]))

    print('\n结果: %d/%d' % (passed, passed + failed))


main()
