"""Finding adb and running it.

Every adb invocation in the plugin goes through `Adb.run`: an absolute
binary, an argv list (never a shell string), `-s SERIAL` on every device
command, a deadline, and a byte cap enforced where the bytes are produced.
A child that outruns the cap is killed and the read is reported as
`too_much_output`, never parsed. A child that outruns the deadline is
terminated, then killed, and reported as `timeout`.

Resolution order (Decisions table): the `adbPath` setting, then
$ANDROID_HOME / $ANDROID_SDK_ROOT `/platform-tools/adb`, then
`~/Android/Sdk/platform-tools/adb`, then PATH. OMARCHY_ANDROID_DEV_PATH
overrides all of them (tests point it at the fake adb; a value that is
not executable means "no adb", so `no_adb` paths can be tested too).
"""

import errno
import fcntl
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

from . import fmt

DEFAULT_TIMEOUT = 10
SERVER_LOCK_CEILING = 10.0
SERVER_STAMP_WINDOW = 10.0


def die_with_parent():
    """PR_SET_PDEATHSIG: SIGTERM from the kernel when the parent thread that
    started us goes away. Linux only, best effort; used by the helper for
    itself (`track`, `record`) and by its long-lived adb children. Those
    children also get SIGINT back at its default: the shell starts its
    processes with SIGINT ignored and an ignored signal survives exec
    (seen 2026-09-05: `record stop` did nothing to the adb child)."""
    import signal
    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except (OSError, ValueError):
        pass
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(1, signal.SIGTERM, 0, 0, 0)
    except (OSError, AttributeError):
        pass


class AdbError(Exception):
    def __init__(self, code, message, stderr=""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stderr = stderr

    def to_dict(self):
        d = {"code": self.code, "message": fmt.clean(self.message, 512)}
        if self.stderr:
            d["stderr"] = fmt.clean(self.stderr, 512)
        return d


class PartialError(AdbError):
    """An AdbError that still carries a payload (status without adb keeps
    its tools and versions)."""

    def __init__(self, payload, cause):
        super().__init__(cause.code, cause.message, cause.stderr)
        self.payload = payload


class Result:
    def __init__(self, argv, code, stdout, stderr, truncated=False, timed_out=False):
        self.argv = argv
        self.code = code
        self.stdout = stdout          # bytes
        self.stderr = stderr          # str, already cleaned and capped
        self.truncated = truncated
        self.timed_out = timed_out

    @property
    def text(self):
        return self.stdout.decode("utf-8", errors="replace")

    def lines(self):
        return fmt.lines(self.text)


# ---- resolution ------------------------------------------------------------

def _executable(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def _setting_path(settings):
    """The adbPath setting as a file path ("" when unset): `~` expanded, a
    directory means the adb inside it."""
    setting = os.path.expanduser(str(settings.get("adbPath") or "").strip())
    if setting and os.path.isdir(setting):
        setting = os.path.join(setting, "adb")
    return setting


def missing_text(settings):
    """The `no_adb` message: why resolve() found nothing and what to do."""
    setting = _setting_path(settings)
    if os.environ.get("OMARCHY_ANDROID_DEV_PATH") is None and setting:
        return f"No adb at {fmt.display_path(setting)}. Fix the adbPath setting, or clear it to look in the SDK and on PATH again"
    return "No adb found. Set adbPath in the plugin settings, or install the android-tools package or the SDK platform-tools"


def resolve(settings):
    """(path, source) or (None, None). `source` is one of override,
    setting, env, home, path."""
    override = os.environ.get("OMARCHY_ANDROID_DEV_PATH")
    if override is not None:
        return (override, "override") if _executable(override) else (None, None)
    setting = _setting_path(settings)
    if setting:
        # An explicit setting is an instruction, not a hint: a path that does
        # not hold adb is reported (`missing_text`), never silently replaced
        # by whatever the SDK or PATH would have given.
        return (setting, "setting") if _executable(setting) else (None, None)
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(var)
        if root:
            candidate = os.path.join(root, "platform-tools", "adb")
            if _executable(candidate):
                return candidate, "env"
    home = os.path.join(os.path.expanduser("~"), "Android", "Sdk", "platform-tools", "adb")
    if _executable(home):
        return home, "home"
    found = shutil.which("adb")
    if found and _executable(found):
        return os.path.realpath(found), "path"
    return None, None


def sdk_root(adb_path):
    """The SDK directory two levels above platform-tools/adb, when it looks like one."""
    if not adb_path:
        return None
    root = os.path.dirname(os.path.dirname(os.path.realpath(adb_path)))
    return root if os.path.isdir(os.path.join(root, "platform-tools")) else None


# ---- the bounded reader ----------------------------------------------------

def _pump(stream, cap, sink, proc):
    """Read `stream` into sink['data'] until EOF or `cap` bytes. Past the cap
    the child is killed: the truncated text is never handed to a parser."""
    fd = stream.fileno()
    data = sink["data"]
    try:
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            room = cap - len(data)
            if len(chunk) > room:
                data += chunk[:max(room, 0)]
                sink["truncated"] = True
                try:
                    proc.kill()
                except OSError:
                    pass
                # Drain so the child can die instead of blocking on the pipe.
                while True:
                    try:
                        if not os.read(fd, 65536):
                            break
                    except OSError:
                        break
                break
            data += chunk
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _debug(msg):
    if os.environ.get("OMARCHY_ANDROID_DEV_DEBUG"):
        sys.stderr.write(f"[android-dev] {msg}\n")
        sys.stderr.flush()


def _kill(proc):
    try:
        proc.terminate()
    except OSError:
        return
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def run_bounded(argv, timeout=DEFAULT_TIMEOUT, cap=fmt.CAP_DEFAULT, stdin=None):
    """Run argv with a deadline and a byte cap on stdout (stderr is capped at
    CAP_STDERR). Returns a Result; raises AdbError(timeout|too_much_output)
    and AdbError(no_adb) when the binary cannot start."""
    started = time.monotonic()
    _debug("run " + " ".join(argv))
    try:
        proc = subprocess.Popen(argv, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    except OSError as e:
        raise AdbError("no_adb", f"Cannot start {argv[0]}: {e.strerror}") from e
    out = {"data": bytearray(), "truncated": False}
    err = {"data": bytearray(), "truncated": False}
    t_out = threading.Thread(target=_pump, args=(proc.stdout, cap, out, proc), daemon=True)
    t_err = threading.Thread(target=_pump, args=(proc.stderr, fmt.CAP_STDERR, err, proc), daemon=True)
    t_out.start()
    t_err.start()
    timed_out = False
    try:
        if timeout is None:
            proc.wait()
        else:
            proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill(proc)
    except BaseException:
        # The whole-run alarm (cli.Deadline) or a Ctrl-C: the child must not
        # go on without us (an `adb install` would otherwise finish unseen).
        _kill(proc)
        raise
    t_out.join(timeout=2)
    t_err.join(timeout=2)
    stderr = fmt.clean(bytes(err["data"]).decode("utf-8", errors="replace").strip(), 4096)
    result = Result(argv, proc.returncode, bytes(out["data"]), stderr, truncated=out["truncated"], timed_out=timed_out)
    _debug(f"exit {proc.returncode} in {time.monotonic() - started:.2f}s, {len(result.stdout)} bytes"
           + (" TRUNCATED" if result.truncated else "") + (" TIMEOUT" if timed_out else ""))
    if result.truncated:
        raise AdbError("too_much_output", f"{os.path.basename(argv[0])} printed more than {cap // 1024} KiB; the output was discarded")
    if timed_out:
        raise AdbError("timeout", f"{os.path.basename(argv[0])} {' '.join(argv[1:3])} did not finish in {timeout:.0f} s")
    return result


# ---- adb ---------------------------------------------------------------------

_FAILURE_PREFIXES = ("Failure", "Error:", "Failed")


def _failed(result):
    if result.code != 0:
        return True
    if "error:" in result.stderr.lower():
        return True
    for line in result.lines():
        s = line.strip()
        if s.startswith(_FAILURE_PREFIXES):
            return True
    return False


def _failure_text(result):
    if result.stderr:
        return result.stderr
    for line in result.lines():
        s = line.strip()
        if s.startswith(_FAILURE_PREFIXES):
            return s
    return f"adb exited with code {result.code}"


def classify(result):
    """An AdbError for a failed Result, with the reviewer-visible codes."""
    text = _failure_text(result)
    low = (result.stderr or "").lower()
    if "unauthorized" in low:
        code = "unauthorized"
    elif "device offline" in low or "device is offline" in low:
        code = "offline"
    elif "no devices/emulators found" in low or ("device" in low and "not found" in low):
        code = "no_device"
    elif "more than one device" in low:
        code = "many_devices"
    else:
        code = "adb_failed"
    return AdbError(code, text, stderr=result.stderr)


def server_port():
    try:
        return int(os.environ.get("ANDROID_ADB_SERVER_PORT") or 5037)
    except ValueError:
        return 5037


def server_up():
    """True when something accepts connections on adb's server port."""
    host = os.environ.get("ANDROID_ADB_SERVER_ADDRESS") or "127.0.0.1"
    try:
        with socket.create_connection((host, server_port()), timeout=0.5):
            return True
    except OSError:
        return False


class Adb:
    def __init__(self, path, source, state=None):
        self.path = path
        self.source = source
        self.state = state
        self._server_checked = False

    def describe(self):
        """The envelope's `adb`: where it is and how it was found, with a
        display line for the panel (`~/Android/Sdk/platform-tools/adb · found in ~/Android/Sdk`)."""
        return {"path": self.path, "source": self.source, "path_text": fmt.display_path(self.path),
                "source_text": fmt.adb_source_text(self.source),
                "text": f"{fmt.display_path(self.path)} · {fmt.adb_source_text(self.source)}"}

    def ensure_server(self):
        """`adb start-server` once per run, under a lock file in the state
        dir, so two clients starting in the same instant at login (the
        tracker and a CLI call, or two shells) cannot both fork a server
        and have one abort on the busy socket. Under the lock the server
        port is probed first, and a stamp written by another holder within
        the last few seconds is trusted, so the second client does nothing."""
        if self._server_checked:
            return
        self._server_checked = True
        lock_path = self.state.lock_path() if self.state and self.state.dir else None
        fd = None
        if lock_path:
            try:
                fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)
            except OSError:
                fd = None
        locked = False
        if fd is not None:
            deadline = time.monotonic() + SERVER_LOCK_CEILING
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError as e:
                    if e.errno not in (errno.EAGAIN, errno.EACCES) or time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
        try:
            if fd is not None:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    stamp = os.read(fd, 64).decode("ascii", errors="replace").strip()
                    if stamp and time.time() - float(stamp) < SERVER_STAMP_WINDOW:
                        _debug("start-server skipped: another client just did it")
                        return
                except (OSError, ValueError):
                    pass
            if server_up():
                _debug("start-server skipped: the server port answers")
                return
            try:
                run_bounded([self.path, "start-server"], timeout=SERVER_LOCK_CEILING)
            except AdbError as e:
                _debug(f"start-server: {e.message}")
            if fd is not None:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.ftruncate(fd, 0)
                    os.write(fd, f"{time.time():.3f}".encode("ascii"))
                except OSError:
                    pass
        finally:
            if fd is not None:
                if locked:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                os.close(fd)

    def run(self, args, serial=None, timeout=DEFAULT_TIMEOUT, cap=fmt.CAP_DEFAULT, check=True):
        argv = [self.path]
        if serial:
            argv += ["-s", serial]
        argv += [str(a) for a in args]
        result = run_bounded(argv, timeout=timeout, cap=cap)
        if check and _failed(result):
            raise classify(result)
        return result

    def shell(self, serial, *cmd, **kw):
        return self.run(["shell", *cmd], serial=serial, **kw)

    def popen(self, args, serial=None):
        """A long-lived child (track-devices); the caller owns it. The child
        asks the kernel for SIGTERM when this helper dies, however it dies:
        the shell ends a helper it no longer wants with SIGKILL, which no
        signal handler can forward (seen 2026-09-05: an orphaned
        `adb track-devices` after disabling the plugin)."""
        argv = [self.path]
        if serial:
            argv += ["-s", serial]
        argv += [str(a) for a in args]
        _debug("popen " + " ".join(argv))
        try:
            return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    close_fds=True, preexec_fn=die_with_parent)
        except OSError as e:
            raise AdbError("no_adb", f"Cannot start {argv[0]}: {e.strerror}") from e

    def version(self):
        """`37.0.1` from `adb version`'s `Version 37.0.1-15733141` line."""
        try:
            result = self.run(["version"], timeout=5)
        except AdbError:
            return None
        for line in result.lines():
            s = line.strip()
            if s.startswith("Version "):
                return fmt.clean(s[len("Version "):].split("-")[0], 32)
        return None
