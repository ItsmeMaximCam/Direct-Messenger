"""
    ("show", "")    open the window
    ("toggle", "")  show or hide the window
    ("exit", "")    quit the app
"""

import ctypes
import threading
from ctypes import wintypes

import pystray
from PIL import Image

#windows API functions for the global hotkey
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000      #holding the keys down only counts as one press
VK_M = 0x4D                #the M key
WM_HOTKEY = 0x0312         #message windows sends when our hotkey is pressed
WM_QUIT = 0x0012           #message we send ourselves to stop the hotkey thread
HOTKEY_ID = 1

hotkey_thread_id = None    #needed to tell the hotkey thread to stop


def start_tray(event_queue, icon_path):
    menu = pystray.Menu(
        # default=True means double-clicking the icon also runs "Open".
        pystray.MenuItem("Open", lambda: event_queue.put(("show", "")), default=True),
        pystray.MenuItem("Exit", lambda: event_queue.put(("exit", ""))),
    )
    icon = pystray.Icon("DirectMessenger", Image.open(icon_path), "Direct Messenger", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


def notify(icon, title, text):
    #shows a notification balloon from the tray icon
    try:
        #Long messages are cut short; Windows truncates them anyway.
        icon.notify(text[:200], title)
    except Exception:
        pass                      #notifications are a nice extra, never fatal


def stop_tray(icon):
    icon.stop()


def register_hotkey(event_queue):
    #registers ctrl+alt+m as a global hotkey to show/hide the window.
    #windows only tells us when that exact combo is pressed. (the old keyboard
    #library watched EVERY key press on the computer, the same way keyloggers work)
    #returns False if another program (or another copy of this app) already uses it
    registered = threading.Event()
    result = {"ok": False}

    def hotkey_loop():
        global hotkey_thread_id
        #windows sends the hotkey message to whichever thread registered it
        result["ok"] = bool(user32.RegisterHotKey(None, HOTKEY_ID,
                                                  MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_M))
        if result["ok"]:
            hotkey_thread_id = kernel32.GetCurrentThreadId()
        registered.set()
        if not result["ok"]:
            return
        #GetMessageW waits for the next message. it returns 0 when it gets WM_QUIT
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY:
                event_queue.put(("toggle", ""))
        user32.UnregisterHotKey(None, HOTKEY_ID)

    threading.Thread(target=hotkey_loop, daemon=True).start()
    registered.wait(timeout=2)
    return result["ok"]


def unregister_hotkey():
    #tells the hotkey thread to stop, it unregisters the hotkey on its way out
    if hotkey_thread_id is not None:
        user32.PostThreadMessageW(hotkey_thread_id, WM_QUIT, 0, 0)
