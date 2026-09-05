#!/usr/bin/python3
"""A fake `adb` for the tests. Pointed at by OMARCHY_ANDROID_DEV_PATH.

OMARCHY_ANDROID_DEV_FAKE_SCRIPT names a JSON file: a list of rules, each
`{"match": "substring of the argv", "stdout": "...", "stdout_file":
"fixture name", "stdout_hex": "hex bytes", "bytes": N, "stderr": "...", "code": 0, "sleep": s,
"sleep_after": s, "file_arg": i, "file_hex": "hex bytes", "stdin": true}`. `file_arg` names the argv
index of a host path to write `file_hex` to (what `adb pull DST` does). The first rule whose `match` is a substring of the
space-joined argv answers; a rule without `match` answers everything.
No matching rule: exit 1 with a message on stderr.

Every call is appended to OMARCHY_ANDROID_DEV_FAKE_LOG as one JSON line
(the argv), so tests can assert the exact arguments, `-s SERIAL` included.
A rule with `stdin: true` reads one line from stdin first (what `adb pair`
does with the code) and logs it as a last element `<stdin>LINE`.
"""

import json
import os
import sys
import time

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def log_call(argv):
    log = os.environ.get("OMARCHY_ANDROID_DEV_FAKE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(argv) + "\n")


def main():
    argv = sys.argv[1:]
    rules = []
    script = os.environ.get("OMARCHY_ANDROID_DEV_FAKE_SCRIPT")
    if script:
        with open(script, "r", encoding="utf-8") as f:
            rules = json.load(f)
    joined = " ".join(argv)
    for rule in rules:
        match = rule.get("match")
        if match is not None and match not in joined:
            continue
        if rule.get("stdin"):
            # What `adb pair` does: one line from stdin (the code). Logged as
            # a marked extra element so a test can pin "on stdin, not argv".
            line = sys.stdin.buffer.readline(64).decode("utf-8", errors="replace").strip()
            log_call(argv + ["<stdin>" + line])
        else:
            log_call(argv)
        if rule.get("sleep"):
            time.sleep(float(rule["sleep"]))
        out = sys.stdout.buffer
        if "stdout_file" in rule:
            with open(os.path.join(FIXTURES, rule["stdout_file"]), "rb") as f:
                out.write(f.read())
        elif "stdout_hex" in rule:
            out.write(bytes.fromhex(rule["stdout_hex"]))
        elif "bytes" in rule:
            n = int(rule["bytes"])
            chunk = b"x" * 65536
            while n > 0:
                out.write(chunk[:n])
                n -= 65536
        elif "stdout" in rule:
            out.write(str(rule["stdout"]).encode("utf-8"))
        out.flush()
        if "file_arg" in rule:
            with open(argv[int(rule["file_arg"])], "wb") as f:
                f.write(bytes.fromhex(rule.get("file_hex", "00")))
        if rule.get("stderr"):
            sys.stderr.write(str(rule["stderr"]))
            sys.stderr.flush()
        if rule.get("sleep_after"):
            time.sleep(float(rule["sleep_after"]))
        return int(rule.get("code", 0))
    log_call(argv)
    sys.stderr.write(f"fake adb: no rule for: {joined}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
