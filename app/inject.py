"""Text injection into the focused app.

Primary method (validated pattern from FreeFlow/whisper-key-local): snapshot the
clipboard, write our text, send Ctrl+V, then restore the previous clipboard after a
delay so slow/Electron apps have read it. Fallback: direct typing via keyboard.write
(SendInput KEYEVENTF_UNICODE under the hood).

Known limits: UIPI blocks injection into elevated windows; non-text clipboard
content (images/files) is not restored — only text snapshots are.
"""
import time

import keyboard
import win32clipboard
import win32con


def _open_clipboard(retries: int = 10, delay: float = 0.05):
    """Clipboard can be held by another app; retry briefly."""
    for i in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:
            time.sleep(delay)
    return False


def _get_clipboard_text(retries: int = 5, delay: float = 0.03) -> str | None:
    for _ in range(retries):
        if not _open_clipboard():
            continue
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            return None  # no text on the clipboard - nothing to snapshot
        except Exception:
            pass  # transient contention - close, wait, retry
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
        time.sleep(delay)
    return None


def _set_clipboard_text(text: str, retries: int = 5, delay: float = 0.03) -> bool:
    """Retry the whole open->empty->set sequence. 'handle is invalid' is
    transient contention (a clipboard manager / Office / browser holding the
    clipboard for the moment between empty and set); a retry clears it. Only if
    every attempt fails does inject() fall back to typing."""
    for _ in range(retries):
        if not _open_clipboard():
            continue
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            return True
        except Exception:
            pass  # transient contention - close, wait, retry
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
        time.sleep(delay)
    return False


def inject(text: str, cfg: dict) -> float:
    """Inject text into the focused app. Returns seconds taken (excl. restore)."""
    t0 = time.time()
    icfg = cfg["inject"]
    if icfg["method"] == "type":
        keyboard.write(text)
        return time.time() - t0

    prior = _get_clipboard_text() if icfg["restore_clipboard"] else None
    if not _set_clipboard_text(text):
        keyboard.write(text)  # clipboard locked hard: fall back to typing
        return time.time() - t0
    keyboard.send("ctrl+v")
    took = time.time() - t0

    if icfg["restore_clipboard"] and prior is not None:
        time.sleep(icfg["restore_delay_s"])  # let the target app read the paste
        _set_clipboard_text(prior)
    return took
