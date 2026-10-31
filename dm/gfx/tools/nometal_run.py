#!/usr/bin/env python3
# 在没有苹果 Metal 编译器的机器上跑着色器出库链（Windows / Linux / 没装 Xcode 的 Mac；给 tools/d2rm_pack.py 用）。
# 用法：nometal_run.py <脚本.py> [参数…]   例：nometal_run.py dmsh_build.py <包目录> <缓存目录>
# 做法：不改出库链的任何一个文件（它们的内容参与翻译链版本，一改内测的着色器库就得整体换代），只在本进程里把它们调外部命令的
# 那一个入口（subprocess.run）接过来，认出下面几条命令自己答，其余原样放行：
#   xcrun -sdk <x> metal --version              → 答「none」（工具指纹里编译器记成不用 → 链版本自成一支，缓存与正常模式互不相混）
#   xcrun -sdk <x> metal -c <源码> -o <中间件>    → 把源码拷成中间件（换行统一成 \n）
#   xcrun -sdk <x> metallib <中间件> -o <库>      → 把中间件原样拷成库
#   which <名字>                                 → 用 Python 自己找
#   cp -c <甲> <乙>                              → 普通拷贝
# 结果：「库文件」（*_b.metallib / *_bf.metallib）里放的是着色器源码。壳（DM_SHELL 构建）的图形层发现库不是编好的就在设备上现编
# （gfx/nvn/nvn_mtl.m），系统会把编好的结果缓存，第二次启动起不再编。
# 少掉的一道：正常模式下苹果编译器顺带验了每份源码能编过；这里不验，编不过的要到设备上用到它时才报红。
# Runs the shader build chain on a machine without Apple's Metal compiler (Windows / Linux / a Mac without Xcode; for use by tools/d2rm_pack.py).
# Usage: nometal_run.py <script.py> [args...]   Example: nometal_run.py dmsh_build.py <package dir> <cache dir>
# How: not a single file of the build chain is modified (their contents feed into the translation chain version, and any change would force a whole new generation of the beta shader libraries); only, within this process, the one entry through which they call external commands
# (subprocess.run) is taken over: the commands below are recognized and answered here, and everything else is passed through unchanged:
#   xcrun -sdk <x> metal --version              → answers "none" (the compiler is recorded as unused in the tool fingerprint → the chain version forms its own branch, and its cache never mixes with normal mode's)
#   xcrun -sdk <x> metal -c <source> -o <intermediate file>    → copies the source as the intermediate file (line endings normalized to LF)
#   xcrun -sdk <x> metallib <intermediate file> -o <library>      → copies the intermediate file verbatim as the library
#   which <name>                                 → looked up by Python itself
#   cp -c <a> <b>                              → ordinary copy
# Result: the "library files" (*_b.metallib / *_bf.metallib) contain shader source. When the graphics layer of the shell (DM_SHELL build) finds that a library is not a compiled one, it compiles it on the device
# (gfx/nvn/nvn_mtl.m); the system caches the compiled result, and from the second launch on nothing is compiled again.
# The one check that is lost: in normal mode Apple's compiler also verifies along the way that every source compiles; here that is not verified, and one that fails to compile only reports a failure when it is used on the device.
import os, runpy, shutil, subprocess, sys

_real = subprocess.run
LINK = not os.environ.get('NOMETAL_NO_LINK')   # 见下方 _link | see _link

# --------------------------------------------------------------------------------------------------------------------
# SPIRV-Cross as a resident worker instead of one process per shader (思路一 + 思路二).
#
# 一个 shader 一次 spirv-cross 进程，实测 60~85 ms 里约 60 ms 是 Windows 建进程 + CRT 启动/退出（本机 cmd /c exit 的地板
# 就是 36.5 ms）。这里把同一个可执行文件的 --daemon 模式（main.cpp 里加了 40 行）当常驻 worker 用：线程从池里借一个、翻
# 译完还回去，请求走 main_inner() 本身，所以参数解析、输出字节、CRLF 换行与 CLI 完全一致。
#
# 为什么在这层拦截而不是改 dmsh_build.py：dmsh_chain.FILES 里有 dmsh_build.py，动它一行 = 链版本换代 = 全部 shader 缓存
# 作废（5 万 shader 重译 45 分钟）；nometal_run.py 不在 FILES 里，在这里拦截零换代。tool_fingerprint() 的
# spirv-cross --version 探测照旧走真 exe，TOOL_FP 与 dmsh_chain.lock 都不变。
#
# 安全网：worker 被杀/崩溃/协议违约 → 这一次调用回退成原版 CLI，并把该 worker 丢弃；连续失败 3 次直接关掉这条快捷路径。
# 只接 capture_output + text + 带 --output 且路径都是绝对路径的调用；其余（--version、无 --output 的 stdout 模式、带
# timeout/check 的）一律原样走 CLI。
#
# A shader per spirv-cross process costs 60-85 ms on Windows, about 60 of it process creation plus CRT start-up and
# teardown (this machine's floor for a do-nothing command is 36.5 ms). The same executable therefore gains a --daemon
# mode (40 lines in main.cpp) and this module keeps a pool of those workers: a thread borrows one, translates, hands it
# back. Requests go through main_inner() itself, so argument handling, output bytes and CRLF line endings are the CLI's
# own.
#
# Intercepting here rather than in dmsh_build.py is what keeps the chain version: dmsh_build.py is in dmsh_chain.FILES, so
# editing it invalidates every shader's cache (50,978 shaders, 45 minutes); nometal_run.py is not, and tool_fingerprint()'s
# spirv-cross --version probe still runs the real executable, so TOOL_FP and dmsh_chain.lock stay as they are.
#
# Safety net: a worker that died, crashed or broke the protocol means that one call falls back to the plain CLI and the
# worker is dropped; three failures in a row disable the shortcut for good. Only capture_output + text calls that carry
# --output with ASCII absolute paths are intercepted - --version, the stdout mode without --output, and anything with
# timeout/check run the CLI unchanged.
import atexit, collections, locale, struct, threading

SPVC_MAX = int(os.environ.get('NOMETAL_SPVC_MAX', '24'))   # 最多这么多常驻进程 | upper bound on resident workers
_SPVC_LOCK = threading.Lock()
_SPVC_IDLE = collections.deque()      # [(spirv_cross path, daemon path, Popen)]
_SPVC_STATS = collections.Counter()
_SPVC_OFF = ''
_SPVC_CODEC = locale.getpreferredencoding(False)


def _spvc_daemon_of(exe):
    """常驻二进制就放在 spirv-cross 旁边；NOMETAL_SPVC_DAEMON 可指到别处，'0' 关掉，'1' 用默认位置。
    The worker sits next to spirv-cross; NOMETAL_SPVC_DAEMON points elsewhere, '0' disables, '1' means the default name."""
    want = os.environ.get('NOMETAL_SPVC_DAEMON', '')
    if want == '0': return None
    path = want if want not in ('', '1') else os.path.join(os.path.dirname(exe) or '.',
                                                           'spirv-cross-daemon.exe' if os.name == 'nt' else 'spirv-cross-daemon')
    return path if os.path.isfile(path) else None


def _spvc_readn(f, n):
    out = b''
    while len(out) < n:
        chunk = f.read(n - len(out))
        if not chunk: raise EOFError('worker closed the pipe')
        out += chunk
    return out


def _spvc_readline(f):
    out = b''
    while True:
        c = f.read(1)
        if not c: raise EOFError('worker closed the pipe')
        if c == b'\n': return out.decode('ascii')
        out += c
        if len(out) > 4096: raise ValueError('worker sent a header that is too long')


def _spvc_spawn(daemon):
    return subprocess.Popen([daemon, '--daemon'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, bufsize=0)


def _spvc_borrow(exe, daemon):
    with _SPVC_LOCK:
        for k, (x_exe, x_daemon, p) in enumerate(_SPVC_IDLE):
            if x_daemon == daemon and x_exe == exe:
                del _SPVC_IDLE[k]; return p
        room = _SPVC_STATS['spawned'] < SPVC_MAX
    if not room: return None   # 池满：这一次走 CLI，绝不阻塞 | pool full: run the CLI, never block
    try: p = _spvc_spawn(daemon)
    except OSError: return None
    with _SPVC_LOCK: _SPVC_STATS['spawned'] += 1
    return p


def _spvc_give_back(exe, daemon, p):
    with _SPVC_LOCK: _SPVC_IDLE.append((exe, daemon, p))


def _spvc_kill(p):
    try: p.kill()
    except OSError: pass
    try: p.wait(timeout=5)
    except Exception:
        try: p.kill()
        except OSError: pass


def _spvc_translate(exe, daemon, argv):
    """一次翻译：→ (returncode, stdout bytes, stderr bytes)；池满时返回 None（调用方走 CLI）。
    One translation: (returncode, stdout bytes, stderr bytes), or None when no worker is free (the caller runs the CLI)."""
    p = _spvc_borrow(exe, daemon)
    if p is None: return None
    blob = b''.join(struct.pack('<I', len(a.encode('utf-8'))) + a.encode('utf-8') for a in argv)
    try:
        p.stdin.write(('%d\n' % len(blob)).encode('ascii') + blob)
        ret, out_len, err_len = (int(x) for x in _spvc_readline(p.stdout).split())
        out = _spvc_readn(p.stdout, out_len)
        err = _spvc_readn(p.stdout, err_len)
    except (OSError, EOFError, ValueError):
        _spvc_kill(p)
        with _SPVC_LOCK: _SPVC_STATS['lost'] += 1
        raise
    _spvc_give_back(exe, daemon, p)
    return ret, out, err


def _spvc_wanted(c, text, kwargs):
    """这次能不能交给常驻 worker：只有 capture_output + text、带 --output、路径都是绝对且 ASCII。
    Whether this call may go to a worker: only the plain capture_output + text shape, with --output and ASCII absolute paths."""
    if not text or not kwargs.get('capture_output'): return False
    if set(kwargs) - {'capture_output', 'text', 'universal_newlines'}: return False
    if not os.path.basename(c[0]).lower().startswith('spirv-cross'): return False
    if '--version' in c or '--help' in c or '--help-msl' in c or '--help-all' in c: return False
    if '--output' not in c: return False   # 无 --output 时结果走 stdout，那条路留在 CLI 上 | stdout mode stays on the CLI
    i = c.index('--output')
    if i == 0 or i + 1 >= len(c): return False
    for path in (c[i - 1], c[i + 1]):
        if path.startswith('-') or not os.path.isabs(path): return False
        try: path.encode('ascii')
        except UnicodeEncodeError: return False   # worker 里是 ANSI fopen：非 ASCII 路径交给 CLI 的宽字符接口 | ANSI fopen keeps non-ASCII on the CLI
    return True


def _spvc_text(b):
    """text=True 的等价解码：按本地编码解码，再做 universal newlines（与今天 CLI 那条路上的 CompletedProcess 一致）。
    The equivalent of text=True: decode with the locale encoding, then translate newlines as text=True does."""
    s = b.decode(_SPVC_CODEC, 'replace')
    return s.replace('\r\n', '\n').replace('\r', '\n')


def _spvc_call(c, kwargs):
    global _SPVC_OFF
    if _SPVC_OFF: return None
    exe = c[0]
    if not os.path.dirname(exe): exe = shutil.which(exe) or exe
    daemon = _spvc_daemon_of(exe)
    if not daemon: return None
    try:
        got = _spvc_translate(exe, daemon, c)
    except Exception:
        with _SPVC_LOCK:
            _SPVC_STATS['fallback'] += 1
            if _SPVC_STATS['fallback'] >= 3 and _SPVC_STATS['calls'] == 0: _SPVC_OFF = 'worker unusable, CLI only'
        return None
    if got is None: return None
    ret, out, err = got
    with _SPVC_LOCK: _SPVC_STATS['calls'] += 1
    return subprocess.CompletedProcess(c, ret, stdout=_spvc_text(out), stderr=_spvc_text(err))


@atexit.register
def _spvc_report():
    with _SPVC_LOCK:
        idle = [p for _, _, p in _SPVC_IDLE]
        _SPVC_IDLE.clear()
        st = dict(_SPVC_STATS)
    for p in idle: _spvc_kill(p)
    if st.get('calls') or st.get('fallback'):
        sys.stderr.write('[nometal] spirv-cross worker: %d calls in %d resident processes, %d fell back to the CLI%s\n'
                         % (st.get('calls', 0), st.get('spawned', 0), st.get('fallback', 0),
                            ' (' + _SPVC_OFF + ')' if _SPVC_OFF else ''))
        sys.stderr.flush()


def _same_volume(src, dst):   # 硬链接只能同卷 | a hardlink needs one volume
    try: return os.stat(src).st_dev == os.stat(os.path.dirname(dst) or '.').st_dev
    except OSError: return False


def _link(src, dst):
    """metallib 那一步不需要另存一份数据：库文件与中间文件字节相同，给同一个 inode 再加个名字即可，调用方随后删掉中间
    文件时删的只是名字，库的数据还在（dmsh_mtlcache.Cache._compile 的 finally）。只做这一步：中间文件是它的源、之后不会
    再被写；源码那一步保持拷贝，因为源码之后可能被就地重写（dmsh_build.finish 的二次编译），链接会把库一起改掉。
    不同卷、目标已存在、文件系统不支持链接（FAT / 网络盘）时回退成拷贝。
    The metallib step needs no second copy of the data: the library is byte-identical to the intermediate file, so the
    same inode gets a second name and the caller's later delete of that file removes only a name (dmsh_mtlcache.Cache.
    _compile's finally). Only this step: the intermediate file is its source and is not written again, whereas the source
    step stays a copy because the source may be rewritten in place afterwards (dmsh_build.finish recompiles with a second
    source) and a link would take the library with it. Different volume, an existing destination, or a filesystem without
    links all fall back to a copy. On Windows a 50,978-shader pack runs this 195,054 times."""
    if not LINK or not _same_volume(src, dst): return False
    try: os.link(src, dst); return True
    except OSError: return False


def _done(args, out=''):
    return subprocess.CompletedProcess(args, 0, stdout=out, stderr='')


def run(args, *a, **k):
    text = k.get('text') or k.get('universal_newlines')
    enc = (lambda s: s) if text else (lambda s: s.encode())
    if isinstance(args, (list, tuple)) and args:
        c = [str(x) for x in args]
        # 常驻 spirv-cross：命中就整条绕过进程创建（见文件头的说明） | resident spirv-cross: skip process creation entirely
        if _spvc_wanted(c, text, k):
            r = _spvc_call(c, k)
            if r is not None: return r
        if c[0] == 'xcrun' and 'metal' in c and '--version' in c: return _done(args, enc('none\n'))
        # dmsh_mtlcache.py fingerprints the toolchain with four probes; without a compiler they answer fixed values, so this
        # branch of the chain version is the same on every machine and its cache never mixes with the compiled one.
        if c[0] == 'xcrun' and 'metallib' in c and '--version' in c: return _done(args, enc('none\n'))
        if c[0] == 'xcrun' and '--show-sdk-version' in c: return _done(args, enc('26.0\n'))
        if c[0] == 'xcrun' and '--show-sdk-build-version' in c: return _done(args, enc('26A000\n'))
        if c[0] == 'xcrun' and 'metal' in c and '-c' in c and '-o' in c:   # 源码 = metal 之后第一个不是选项、也不是 -o 的值的参数（iOS 那条命令在 -c 后面还带一个版本选项） | source = the first argument after metal that is neither an option nor the value of -o (the iOS command also carries a version option after -c)
            o = c.index('-o'); src = [x for i, x in enumerate(c[c.index('metal') + 1:], c.index('metal') + 1) if not x.startswith('-') and i != o + 1]
            if len(src) != 1: raise RuntimeError('nometal_run：认不出源码参数 %r' % c)
            with open(src[0], 'rb') as f: b = f.read()
            with open(c[o + 1], 'wb') as f: f.write(b.replace(b'\r\n', b'\n'))   # Windows 上 spirv-cross 写出的源码是 \r\n 换行：进安装包前归一，同样的输入各系统出的包才相同 | On Windows spirv-cross writes sources with CRLF line endings: normalize before they go into the install package, so the same input gives the same package on every system
            return _done(args, enc(''))
        if c[0] == 'xcrun' and 'metallib' in c and '-o' in c:
            a1, a2 = c[c.index('metallib') + 1], c[c.index('-o') + 1]
            if not _link(a1, a2): shutil.copyfile(a1, a2)
            return _done(args, enc(''))
        if c[0] == 'xcrun': raise RuntimeError('nometal_run：没认出的 xcrun 命令 %r' % c)
        if c[0] == 'which' and len(c) == 2: return _done(args, enc((shutil.which(c[1]) or '') + '\n'))
        if c[0] == 'cp' and len(c) == 4 and c[1] == '-c': shutil.copyfile(c[2], c[3]); return _done(args, enc(''))
    return _real(args, *a, **k)


if __name__ == '__main__':
    if len(sys.argv) < 2: sys.exit(__doc__ or '用法：nometal_run.py <脚本.py> [参数…]')
    subprocess.run = run
    script = os.path.abspath(sys.argv[1]); sys.argv = sys.argv[1:]; sys.path.insert(0, os.path.dirname(script))
    runpy.run_path(script, run_name='__main__')
