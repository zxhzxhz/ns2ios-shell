#!/usr/bin/env python3
# 用 Apple 的 Metal Developer Tools for Windows 真编译 iOS metallib（本机没有 Xcode 时的那条路）。
#
# 用法：metal_win_run.py <脚本.py> [参数…]   例：metal_win_run.py dmsh_build.py <包目录> <缓存目录> [key…]
#
# 与 nometal_run.py 的分工：那个是「没有编译器」的分支（库文件里放源码，设备上现编）；这个是「有编译器」的分支，产物是真的
# MTLB。两者都只在 subprocess.run 这一层拦截，**不改 dmsh_build.py / ios_metal.py / dmsh_chain.py**：这些文件的内容参与
# 翻译链版本的哈希，动一行就要整代着色器库作废。
#
# 拦截的命令（xcrun 的形状与 macOS 上完全一致，所以上层代码一行不用改）：
#   xcrun -sdk <sdk> metal --version           → 真 metal.exe --version 的输出（工具指纹据此记录真实版本）
#   xcrun -sdk <sdk> metallib --version       → 真 metallib.exe --version
#   xcrun --show-sdk-version / --show-sdk-build-version
#   xcrun -sdk <sdk> metal -c … -o <air>      → metal.exe -target air64-apple-ios<V> -c …
#   xcrun -sdk <sdk> metallib <air> -o <lib>  → metallib.exe <air> -o <lib>
# 其余（spirv-cross、which、cp）原样放行；spirv-cross 走 nometal_run.py 里的常驻 worker 池（每 shader 省 60~85 ms 建进程）。
#
# Windows 版工具**没有 SDK 目录**，只有 `-target <triple>`：iOS 是 air64-apple-ios<V>，macOS 是 air64-apple-macos<V>。
# 所以 `-mios-version-min=X` / `-mmacosx-version-min=X` 在这里被换成对应的 -target，其余参数原样透传。
# 工具版本要与目标系统对得上（本机 6.2 / Xcode 26.2，能编 iOS 18+ 目标）。
# 默认直连 <root>/metal/<版本>/bin 里的真身，跳过 bin/ 那层 42 KB 的版本选择壳：每个 shader 少一次进程启动（约 120 ms），
# 产物逐字节相同。METAL_WIN_BIN 给了就按老规矩原样用（指向哪个 bin 目录就用哪个）。
import os, re, runpy, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nometal_run as nm                          # 只为复用它的 spirv-cross 常驻池（import 不会替换 subprocess.run）

_real = subprocess.run
ROOT = r'I:\APP\Metal Developer Tools'


def _real_bin(root):
    """<root>/bin 里的 metal.exe 只是个 42 KB 的版本选择壳：它再拉起 <root>/metal/<版本>/bin 里的真身（119 MB）。
    直连真身省掉那次多余的进程启动（--version 实测 177 ms → 118 ms，每个 shader 少 120 ms），产物字节完全相同
    （air 与 metallib 都比对过）。装了多个版本时取最高的一个；目录形状对不上就退回 <root>/bin。"""
    d = os.path.join(root, 'metal')
    try:
        vs = [v for v in os.listdir(d)
              if all(os.path.isfile(os.path.join(d, v, 'bin', n)) for n in ('metal.exe', 'metallib.exe'))]
    except OSError:
        vs = []
    if not vs: return os.path.join(root, 'bin')
    return os.path.join(d, max(vs, key=lambda v: [int(x) for x in re.findall(r'\d+', v)]), 'bin')


BIN = os.environ.get('METAL_WIN_BIN') or _real_bin(ROOT)     # METAL_WIN_BIN 仍按老规矩指向一个 bin 目录
METAL = os.path.join(BIN, 'metal.exe')
METALLIB = os.path.join(BIN, 'metallib.exe')
DEFAULT_IOS = os.environ.get('METAL_WIN_IOS', '18.0')     # 命令行没给版本时的 iOS deployment target


def _done(args, out=''):
    return subprocess.CompletedProcess(args, 0, stdout=out, stderr='')


def _ver(args, exe, text):
    """工具指纹探测的回答。

    默认答 "none"：dmsh_chain.lock 里 metal 两行也是 none，dmsh_build.py 的锁检查才放行，**链版本 V 保持 8878ca0a4c67**
    —— 已装好的壳把它编译进了二进制（gfx/nvn/nvm_mtl.m 的 DMSH_CHAIN），V 一变，壳就只在 msl/ 下找 b-<新V>，现装的包
    加一个换了 V 的库目录会一个都加载不到。产物是真 MTLB，与 V 无关。
    ⚠ 因此**必须给一个全新的缓存目录**（dmsh_build.py 的第二个参数）：缓存键里带着这个 "none" 指纹，用旧缓存会命中上一轮
    以源码当库的条目。
    METAL_WIN_VERSION=real 时答真实版本号（给 tool_lock.py 看真指纹用，不要配 dmsh_build.py 跑）。"""
    if os.environ.get('METAL_WIN_VERSION', 'none') != 'real':
        return 'none\n' if text else b'none\n'
    r = _real([exe, '--version'], capture_output=True)
    out = (r.stdout or b'') + (r.stderr or b'')
    return out.decode('utf-8', 'replace') if text else out


def _text(r, text):
    """把真工具的字节输出变成 text=True 该有的样子"""
    if not text: return r
    return subprocess.CompletedProcess(r.args, r.returncode,
                                       stdout=(r.stdout or b'').decode('utf-8', 'replace'),
                                       stderr=(r.stderr or b'').decode('utf-8', 'replace'))


def _triple(c):
    """xcrun 形状 → (sdk, target triple, 去掉 -mios-version-min 之后的 metal 参数)"""
    sdk = 'iphoneos'
    if len(c) > 2 and c[1] == '-sdk': sdk = c[2]
    tail, ver = [], None
    for a in c[c.index('metal') + 1:] if 'metal' in c else c:
        if a.startswith('-mios-version-min='):
            ver = a.split('=', 1)[1]; continue
        if a.startswith('-mmacosx-version-min='):
            return 'macosx', 'air64-apple-macos' + a.split('=', 1)[1], tail
        tail.append(a)
    if sdk in ('iphoneos', 'iphonesimulator'):
        return sdk, 'air64-apple-ios%s%s' % (ver or DEFAULT_IOS, '-simulator' if sdk == 'iphonesimulator' else ''), tail
    return sdk, 'air64-apple-macos' + (ver or '14.0'), tail


def run(args, *a, **k):
    text = bool(k.get('text') or k.get('universal_newlines'))
    if isinstance(args, (list, tuple)) and args:
        c = [str(x) for x in args]
        # spirv-cross：交给 nometal_run.py 的常驻 worker（命中就完全不建进程）
        if nm._spvc_wanted(c, text, k):
            r = nm._spvc_call(c, k)
            if r is not None: return r
        if c[0] == 'xcrun':
            if 'metal' in c and '--version' in c:
                return _done(args, _ver(args, METAL, text))
            if 'metallib' in c and '--version' in c:
                return _done(args, _ver(args, METALLIB, text))
            if '--show-sdk-version' in c: return _done(args, DEFAULT_IOS + '\n' if text else (DEFAULT_IOS + '\n').encode())
            if '--show-sdk-build-version' in c: return _done(args, '26A0000\n' if text else b'26A0000\n')
            if 'metal' in c and '-c' in c and '-o' in c:
                sdk, triple, tail = _triple(c)
                r = _real([METAL, '-target', triple] + tail, capture_output=True, **{kk: vv for kk, vv in k.items() if kk in ('cwd', 'timeout', 'env')})
                if r.returncode:
                    sys.stderr.write('[metal_win] metal failed (%s): %s\n'
                                     % (os.path.basename(tail[tail.index('-o') - 1]), (r.stderr or b'').decode('utf-8', 'replace')[:400]))
                return _text(r, text)
            if 'metallib' in c and '-o' in c:
                r = _real([METALLIB] + c[c.index('metallib') + 1:], capture_output=True,
                          **{kk: vv for kk, vv in k.items() if kk in ('cwd', 'timeout', 'env')})
                if r.returncode:
                    sys.stderr.write('[metal_win] metallib failed: %s\n' % (r.stderr or b'').decode('utf-8', 'replace')[:400])
                return _text(r, text)
            raise RuntimeError('metal_win_run：没认出的 xcrun 命令 %r' % c)
        if c[0] == 'which' and len(c) == 2: return _done(args, (shutil.which(c[1]) or '') + ('\n' if text else ''))
        if c[0] == 'cp' and len(c) == 4 and c[1] == '-c': shutil.copyfile(c[2], c[3]); return _done(args, '')
    return _real(args, *a, **k)


if __name__ == '__main__':
    if len(sys.argv) < 2: sys.exit(__doc__ or '用法：metal_win_run.py <脚本.py> [参数…]')
    for p in (METAL, METALLIB):
        if not os.path.isfile(p): sys.exit('metal_win_run：找不到 %s（用 METAL_WIN_BIN 指向 bin 目录）' % p)
    subprocess.run = run
    script = os.path.abspath(sys.argv[1]); sys.argv = sys.argv[1:]; sys.path.insert(0, os.path.dirname(script))
    runpy.run_path(script, run_name='__main__')
