#python main.py                 normal usage
#python main.py --port 5051     use to talk on the same device if needed

import argparse
import queue
import tkinter as tk

import network
import settings
import tray
from gui import ChatWindow
from images import resource_path


def main():
    parser = argparse.ArgumentParser(description="A tiny LAN chat")
    parser.add_argument("--port", type=int, default=network.DEFAULT_PORT,
                        help="TCP port to listen on (default 5050)")
    args = parser.parse_args()

    #one queue carries events from every background thread to the GUI.
    event_queue = queue.Queue()

    messenger = network.Messenger(event_queue, port=args.port)
    root = tk.Tk()
    icon_path = resource_path("app.ico")
    root.iconbitmap(default=icon_path)

    tray_icon = tray.start_tray(event_queue, icon_path)
    window = ChatWindow(root, messenger, event_queue, settings.load_settings(),
                        notify_callback=lambda title, text: tray.notify(tray_icon, title, text),
                        save_callback=settings.save_settings)

    def exit_app():
        #shuts down everything cleanly
        messenger.stop()
        tray.unregister_hotkey()
        tray.stop_tray(tray_icon)
        root.destroy()

    window.on_exit = exit_app

    #Closing the window hides it to the tray instead of deleting it fully.
    root.protocol("WM_DELETE_WINDOW", window.hide)

    if tray.register_hotkey(event_queue):
        window.add_line("system", "Press Ctrl+Alt+M to show or hide this window.")
    else:
        #e.g. another copy of this app is already using it
        window.add_line("system", "Ctrl+Alt+M is already used by another program, "
                                  "so the shortcut is off in this window.")

    messenger.start()
    window.poll_events()
    root.mainloop()


if __name__ == "__main__":
    main()
