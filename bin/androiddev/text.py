"""Send text: `adb shell input text` with the escaping it needs. Android's
`input text` takes one line of ASCII (a `%s` in it is a space); anything
else is refused with a plain message rather than typed wrong. The
clipboard comes from `wl-paste --no-newline`."""

import shlex

from . import fmt
from .adb import AdbError, run_bounded
from .notify import wl_paste_path

MAX_TEXT = 500
CAP_CLIPBOARD = 64 * 1024


def check(text):
    """The text `input text` can type, or AdbError(bad_args)."""
    if text is None or text == "":
        raise AdbError("bad_args", "Nothing to send")
    if len(text) > MAX_TEXT:
        raise AdbError("bad_args", f"input text types at most {MAX_TEXT} characters at a time ({len(text)} given)")
    if "\n" in text or "\r" in text:
        raise AdbError("bad_args", "input text types one line; the text has line breaks")
    bad = [c for c in text if ord(c) < 0x20 or ord(c) > 0x7e]
    if bad:
        raise AdbError("bad_args", "Android's input text types ASCII only; the text has other characters"
                       + (f" ({fmt.clean(''.join(bad[:5]), 5)})" if any(ord(c) > 0x7e for c in bad) else ""))
    return text


def encode(text):
    """What goes after `input text` on the device shell: spaces as `%s`
    (input's own escape), then quoted for the remote shell, which parses
    the joined arguments before `input` sees them."""
    return shlex.quote(text.replace(" ", "%s"))


def send(adb, serial, text, source="text"):
    check(text)
    try:
        adb.shell(serial, "input", "text", encode(text), timeout=30)
    except AdbError as e:
        raise AdbError(e.code, f"Could not type the text: {e.message}", e.stderr) from e
    shown = fmt.clean(text, 60) + ("…" if len(text) > 60 else "")
    return {"notice": f"Sent the clipboard: {shown}" if source == "clipboard" else f"Sent: {shown}", "text": text, "source": source, "length": len(text)}


def clipboard_text():
    """The clipboard as text, or AdbError: no_tool without wl-paste,
    bad_args when it is empty or not text."""
    tool = wl_paste_path()
    if not tool:
        raise AdbError("no_tool", "wl-paste is not installed")
    # `-t text` asks for any text type; an image on the clipboard is then a
    # clear refusal ("not available as requested type") instead of bytes.
    try:
        result = run_bounded([tool, "--no-newline", "-t", "text"], timeout=5, cap=CAP_CLIPBOARD)
    except AdbError as e:
        if e.code == "too_much_output":
            raise AdbError("bad_args", "The clipboard holds more than 64 KiB; input text cannot type that") from e
        raise AdbError("no_tool", f"wl-paste failed: {e.message}") from e
    if result.code != 0:
        low = (result.stderr or "").lower()
        if "nothing" in low:
            raise AdbError("bad_args", "The clipboard is empty")
        if "not available" in low or "requested type" in low:
            raise AdbError("bad_args", "The clipboard does not hold text")
        raise AdbError("bad_args", f"wl-paste failed: {result.stderr or result.code}")
    try:
        text = result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise AdbError("bad_args", "The clipboard does not hold text") from None
    if text == "":
        raise AdbError("bad_args", "The clipboard is empty")
    return text
