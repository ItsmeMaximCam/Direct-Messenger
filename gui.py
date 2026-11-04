import queue
import time
import tkinter as tk
from tkinter import colorchooser
from tkinter import font as tkfont

from PIL import ImageTk

import network
from hearts import Hearts
from images import load_png, tint_image

WINDOW_BG = "#ece9d8"
LOG_BG = "#ffffff"
FONT = ("Tahoma", 9)
FONT_BOLD = ("Tahoma", 9, "bold")
FONT_SMALL_ITALIC = ("Tahoma", 8, "italic")
STATUS_COLOURS = {
    "Disconnected": "#a00000",
    "Connecting...": "#a06000",
    "Connected": "#006000",
}

#Used for the peer until they send their profile.
DEFAULT_PEER_COLOUR = "#000000"

WINDOW_WIDTH = 380
WINDOW_HEIGHT = 420
POLL_INTERVAL_MS = 100
ICON_SIZE = 16               #smallest chat icon size in pixels
TYPING_SEND_INTERVAL = 1.5   #delay between typing notices
TYPING_SHOW_MS = 3000        #how long typing notice stays after the last notice

#Nudge
SHAKE_OFFSETS = [(-10, 0), (10, 0), (-8, 4), (8, -4), (-6, 0), (6, 0),
                 (-4, 2), (4, -2), (-2, 0), (2, 0), (0, 0)]
SHAKE_STEP_MS = 35
NUDGE_COOLDOWN = 3.0         #seconds between nudges, sent OR received
HEART_COOLDOWN = 1.0         #seconds between heart bursts, sent OR received

#limits so a peer spamming us can't slow the app down or eat memory
MAX_LOG_LINES = 1000         #oldest chat lines get removed after this
MAX_PEER_COLOURS = 50        #different colours a peer can use per session
NOTIFY_COOLDOWN = 3.0        #seconds between tray notifications


def readable_text_colour(background):
    #black or white, whichever is easier to read on the given colour
    red, green, blue = (int(background[i:i + 2], 16) for i in (1, 3, 5))
    brightness = 0.299 * red + 0.587 * green + 0.114 * blue
    return "#000000" if brightness > 140 else "#ffffff"


class ChatWindow:
    #the main window, holds the widgets and reacts to queued events

    def __init__(self, root, messenger, event_queue, user_settings,
                 notify_callback=None, save_callback=None):
        self.root = root
        self.messenger = messenger
        self.event_queue = event_queue
        #user_settings is a dict with "name" and "colour"
        self.settings = user_settings
        #notify_callback(title, text) shows a tray notification (can be None)
        self.notify_callback = notify_callback
        #save_callback(settings) saves settings to disc (can be None)
        self.save_callback = save_callback
        #on_exit is set by main.py so the window can ask the app to quit
        self.on_exit = None

        #info about the person we're talking to
        self.peer_ip = ""
        self.peer_name = ""
        self.peer_colour = DEFAULT_PEER_COLOUR
        self.peer_profile_received = False

        self.typing_hide_job = None
        self.shaking = False
        self.incognito = tk.BooleanVar(master=self.root, value=False)
        #when each cooldown action last happened, see _ready()
        self.last_done = {}

        #the icon is as tall as a line of text, so it scales on high-DPI screens too
        line_height = tkfont.Font(root=self.root, font=FONT).metrics("linespace")
        self.base_icon = load_png("user.png", max(ICON_SIZE, line_height))
        #tkinter forgets images python doesn't hold onto, so keep one per colour here
        self.icon_cache = {}
        self.hearts = Hearts(self.root, line_height)

        self.root.title(f"Direct Messenger (port {self.messenger.port})")
        self.root.configure(bg=WINDOW_BG)
        self._build_widgets()
        self._set_status("Disconnected")
        self._place_window()

    #Window and widget setup
    def _place_window(self):
        #sizes the window to fit its widgets and puts it near the bottom right corner
        #on high-DPI screens the widgets need more room than WINDOW_WIDTH, so use the bigger one
        self.root.update_idletasks()
        width = max(WINDOW_WIDTH, self.root.winfo_reqwidth())
        height = max(WINDOW_HEIGHT, self.root.winfo_reqheight())
        self.root.minsize(width, 280)
        x = self.root.winfo_screenwidth() - width - 20
        y = self.root.winfo_screenheight() - height - 80      #stay above the taskbar
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _row(self, side="top", pady=2):
        #makes one horizontal row of widgets
        row = tk.Frame(self.root, bg=WINDOW_BG)
        row.pack(side=side, fill="x", padx=6, pady=pady)
        return row

    def _button(self, row, text, width, command, padx=(2, 0)):
        button = tk.Button(row, text=text, font=FONT, width=width, command=command)
        button.pack(side="left", padx=padx)
        return button

    def _entry(self, row, label, text, width, on_enter):
        #a label + text box that stretches, Enter runs on_enter
        tk.Label(row, text=label, bg=WINDOW_BG, font=FONT, width=7,
                 anchor="w").pack(side="left")
        entry = tk.Entry(row, font=FONT, width=width)
        entry.insert(0, text)
        entry.pack(side="left", padx=4, fill="x", expand=True)
        entry.bind("<Return>", lambda event: on_enter())
        return entry

    def _build_widgets(self):
        #peer IP + connect
        row = self._row(pady=(6, 2))
        self.address_entry = self._entry(row, "Peer IP:", "127.0.0.1", 12, self.on_connect_clicked)
        self.connect_button = self._button(row, "Connect", 9, self.on_connect_clicked, padx=0)

        #name, colour and my IP. the colour button's background shows your current colour
        row = self._row()
        self.name_entry = self._entry(row, "Name:", self.settings["name"], 10, self.apply_name)
        self.name_entry.bind("<FocusOut>", lambda event: self.apply_name())
        self.colour_button = self._button(row, "Colour", 7, self.choose_colour, padx=0)
        self._update_colour_button()
        self._button(row, "My IP", 6, self.on_my_ip_clicked, padx=(4, 0))

        #status line
        self.status_label = tk.Label(self.root, text="", bg=WINDOW_BG, font=FONT_BOLD, anchor="w")
        self.status_label.pack(fill="x", padx=6)

        #bottom widgets are packed before the log so they stay visible when the window is small
        row = self._row(side="bottom", pady=(0, 6))
        self.message_text = tk.StringVar()
        self.message_text.trace_add("write", lambda *args: self.on_message_typed())
        self.message_entry = tk.Entry(row, font=FONT, width=12, textvariable=self.message_text)
        self.message_entry.pack(side="left", fill="x", expand=True)
        self.message_entry.bind("<Return>", lambda event: self.on_send_clicked())
        tk.Button(row, image=self.hearts.button_image, width=28,
                  command=self.on_heart_clicked).pack(side="left", padx=(4, 0), fill="y")
        self._button(row, "Nudge", 6, self.on_nudge_clicked)
        self._button(row, "Send", 6, self.on_send_clicked)

        #typing indicator (left) and incognito checkbox (right)
        row = self._row(side="bottom", pady=0)
        tk.Checkbutton(row, text="Incognito", variable=self.incognito, font=FONT,
                       bg=WINDOW_BG, activebackground=WINDOW_BG).pack(side="right")
        self.typing_label = tk.Label(row, text="", bg=WINDOW_BG, fg="#606060",
                                     font=FONT_SMALL_ITALIC, anchor="w")
        self.typing_label.pack(side="left", fill="x", expand=True)

        self._build_chat_log()

    def _build_chat_log(self):
        frame = tk.Frame(self.root, bg=WINDOW_BG)
        frame.pack(fill="both", expand=True, padx=6, pady=2)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        #width/height are just minimums, the log stretches to fill the window
        self.chat_log = tk.Text(frame, font=FONT, bg=LOG_BG, wrap="word",
                                width=1, height=1, state="disabled", relief="sunken",
                                borderwidth=2, yscrollcommand=scrollbar.set, spacing1=2)
        self.chat_log.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.chat_log.yview)

        self.chat_log.tag_configure("system", foreground="#707070")
        self.chat_log.tag_configure("heart", foreground="#e0245e")
        self.chat_log.tag_configure("secure", foreground="#006000")   #safety code lines
        self.chat_log.tag_configure("bold", font=FONT_BOLD)
        #incognito text gets two tags: "secret" never changes and marks where it is,
        #"hidden" is the black bar, taken off while the mouse is over the message
        self.chat_log.tag_configure("secret", background="#f0f0f0")
        self.chat_log.tag_configure("hidden", background="#000000", foreground="#000000")
        self.chat_log.tag_bind("secret", "<Enter>", lambda event: self._reveal_secret())
        self.chat_log.tag_bind("secret", "<Leave>", lambda event: self._hide_secrets())

    #Button handlers
    def on_connect_clicked(self):
        if self.messenger.is_connected():
            self.messenger.disconnect()
            return

        address = network.parse_address(self.address_entry.get())
        if address is None:
            self.add_line("system", "Enter an IP address like 192.168.1.20 "
                                    "or 127.0.0.1:5051.")
            return
        host, port = address
        self.messenger.connect(host, port)

    def on_send_clicked(self):
        text = self.message_entry.get().strip()
        if not text:
            return
        incognito = self.incognito.get()
        if self.messenger.send_message(text, incognito):
            self.add_chat_message(self.settings["name"], text, self.settings["colour"],
                                  incognito)
            self.message_entry.delete(0, "end")

    def on_my_ip_clicked(self):
        ip = network.get_lan_ip()
        if ip is None:
            self.add_line("system", "Network IP unavailable.")
            return
        #only show the port if it isn't the normal 5050
        if self.messenger.port != network.DEFAULT_PORT:
            ip = f"{ip}:{self.messenger.port}"
        self.root.clipboard_clear()
        self.root.clipboard_append(ip)
        self.add_line("system", f"Your IP on this network is {ip} "
                                "(copied to clipboard)")

    def on_message_typed(self):
        #tells the peer we're typing, at most once every TYPING_SEND_INTERVAL
        if self.message_text.get() and self._ready("typing", TYPING_SEND_INTERVAL):
            self.messenger.send_typing()

    def on_nudge_clicked(self):
        if self._ready("nudge sent", NUDGE_COOLDOWN) and self.messenger.send_nudge():
            self.add_line("system", "You sent a nudge!")
            self.shake_window()

    def on_heart_clicked(self):
        if self._ready("heart sent", HEART_COOLDOWN) and self.messenger.send_heart():
            self.add_line("heart", "♥ You sent hearts!")
            self.hearts.launch(self.chat_log)

    def _ready(self, action, cooldown):
        #True if action hasn't happened in the last cooldown seconds, then starts
        #the cooldown again. stops people (or a hacked app) spamming us
        now = time.monotonic()
        if now - self.last_done.get(action, float("-inf")) < cooldown:
            return False
        self.last_done[action] = now
        return True

    #Name and colour
    def apply_name(self):
        new_name = network.clean_name(self.name_entry.get())
        if not new_name:
            new_name = self.settings["name"]       #don't allow an empty name
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, new_name)
        if new_name != self.settings["name"]:
            self.settings["name"] = new_name
            self._settings_changed()

    def choose_colour(self):
        _, chosen = colorchooser.askcolor(color=self.settings["colour"],
                                          title="Choose your colour", parent=self.root)
        if chosen:   #None if the user pressed Cancel
            self.settings["colour"] = chosen.lower()
            self._update_colour_button()
            self._settings_changed()

    def _update_colour_button(self):
        colour = self.settings["colour"]
        self.colour_button.configure(bg=colour, activebackground=colour,
                                     fg=readable_text_colour(colour))

    def _settings_changed(self):
        #saves the new settings and tells the peer about them
        if self.save_callback:
            self.save_callback(self.settings)
        self._send_profile()

    def _send_profile(self):
        self.messenger.send_profile(self.settings["name"], self.settings["colour"])

    #Showing, hiding and shaking
    def is_hidden(self):
        #"withdrawn" = hidden to tray, "iconic" = minimised to the taskbar
        return self.root.state() in ("withdrawn", "iconic")

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.message_entry.focus_set()

    def hide(self):
        self.root.withdraw()

    def toggle(self):
        if self.is_hidden():
            self.show()
        else:
            self.hide()

    def receive_nudge(self):
        #the peer nudged us, pop the window up in front of everything and shake it
        if not self._ready("nudge received", NUDGE_COOLDOWN):
            return
        self.add_line("system", f"{self.peer_name} sent you a nudge!")
        self.show()
        #being "topmost" for a moment makes sure it shows over other windows
        self.root.attributes("-topmost", True)
        self.root.after(800, lambda: self.root.attributes("-topmost", False))
        self.shake_window()

    def shake_window(self):
        #wiggles the window around its current spot, then puts it back
        if self.shaking:
            return
        self.shaking = True
        self.root.update_idletasks()
        start_x, start_y = self.root.winfo_x(), self.root.winfo_y()

        def shake_step(step):
            if step == len(SHAKE_OFFSETS):
                self.root.geometry(f"+{start_x}+{start_y}")
                self.shaking = False
                return
            offset_x, offset_y = SHAKE_OFFSETS[step]
            self.root.geometry(f"+{start_x + offset_x}+{start_y + offset_y}")
            self.root.after(SHAKE_STEP_MS, shake_step, step + 1)

        shake_step(0)

    #Chat log, typing indicator and status
    def _icon_for(self, colour):
        #returns a coloured person icon, made once per colour then reused
        if colour not in self.icon_cache:
            tinted = tint_image(self.base_icon, colour)
            self.icon_cache[colour] = ImageTk.PhotoImage(tinted, master=self.root)
        return self.icon_cache[colour]

    def _colour_tag(self, colour):
        #makes (once) and returns a text tag for a colour, e.g. "fg#3a7bd5"
        tag = "fg" + colour
        if tag not in self.chat_log.tag_names():
            self.chat_log.tag_configure(tag, foreground=colour)
            #newer tags win over older ones, so put the black bar and the selection
            #highlight back on top (dragging over a black bar shows it too)
            self.chat_log.tag_raise("hidden")
            self.chat_log.tag_raise("sel")
        return tag

    def add_chat_message(self, name, text, colour, incognito=False):
        #adds "[12:30] <icon> Name: text" to the chat log, all in one colour
        #incognito text is a black bar until the mouse is over it
        colour_tag = self._colour_tag(colour)
        text_tags = (colour_tag, "secret", "hidden") if incognito else colour_tag
        self._write_line([(f" {name}: ", (colour_tag, "bold")), (text, text_tags)],
                         icon=self._icon_for(colour))

    def add_line(self, tag, text):
        #adds a timestamped system line to the chat log
        self._write_line([(text, tag)])

    def _write_line(self, pieces, icon=None):
        #adds one timestamped line made of (text, tags) pieces, then removes the
        #oldest lines so the log (and memory) can't grow forever
        log = self.chat_log
        log.configure(state="normal")
        log.insert("end", time.strftime("[%H:%M] "), "system")
        if icon:
            log.image_create("end", image=icon, padx=2)
        for text, tags in pieces:
            log.insert("end", text, tags)
        log.insert("end", "\n")
        extra_lines = int(log.index("end-1c").split(".")[0]) - 1 - MAX_LOG_LINES
        if extra_lines > 0:
            log.delete("1.0", f"{extra_lines + 1}.0")
        log.configure(state="disabled")
        log.see("end")

    def _reveal_secret(self):
        #shows the incognito message under the mouse
        message = self.chat_log.tag_prevrange("secret", "current + 1c")
        if message:
            self.chat_log.tag_remove("hidden", *message)

    def _hide_secrets(self):
        #puts the black bar back over every incognito message
        ranges = self.chat_log.tag_ranges("secret")
        for start, end in zip(ranges[0::2], ranges[1::2]):
            self.chat_log.tag_add("hidden", start, end)

    def show_typing(self):
        self.typing_label.configure(text=f"{self.peer_name} is typing...")
        #restart the countdown that hides the indicator
        if self.typing_hide_job is not None:
            self.root.after_cancel(self.typing_hide_job)
        self.typing_hide_job = self.root.after(TYPING_SHOW_MS, self.hide_typing)

    def hide_typing(self):
        self.typing_label.configure(text="")
        if self.typing_hide_job is not None:
            self.root.after_cancel(self.typing_hide_job)
            self.typing_hide_job = None

    def _set_status(self, status, detail=""):
        text = f"Status: {status}" + (f" - {detail}" if detail else "")
        self.status_label.configure(text=text, fg=STATUS_COLOURS.get(status, "black"))

        #the Connect button doubles as a Disconnect button
        if status == "Connected":
            self.connect_button.configure(text="Disconnect", state="normal")
        elif status == "Connecting...":
            self.connect_button.configure(text="Connect", state="disabled")
        else:
            self.connect_button.configure(text="Connect", state="normal")

    #Event queue (runs on the main thread)
    def poll_events(self):
        #handles every waiting event, then checks again in 100ms
        while True:
            try:
                kind, data = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self.handle_event(kind, data)
        self.root.after(POLL_INTERVAL_MS, self.poll_events)

    def handle_event(self, kind, data):
        if kind in ("message", "incognito"):
            incognito = kind == "incognito"
            self.hide_typing()
            self.add_chat_message(self.peer_name, data, self.peer_colour, incognito)
            #don't put incognito text in the notification
            self._notify_if_hidden(f"Message from {self.peer_name}",
                                   "(incognito message)" if incognito else data)
        elif kind == "typing":
            self.show_typing()
        elif kind == "nudge":
            self.receive_nudge()
        elif kind == "heart" and self._ready("heart received", HEART_COOLDOWN):
            self.add_line("heart", f"♥ {self.peer_name} sent you hearts!")
            self._notify_if_hidden(f"{self.peer_name} sent you hearts", "♥ ♥ ♥")
            self.hearts.launch(self.chat_log)
        elif kind == "profile":
            self.on_peer_profile(*data)
        elif kind == "connected":
            self.on_connected(data)
        elif kind == "secure":
            self.show_safety_code(data)
        elif kind == "connecting":
            self._set_status("Connecting...", data)
        elif kind == "disconnected":
            self.hide_typing()
            self._set_status("Disconnected")
            self.add_line("system", data)
        elif kind in ("listening", "info", "error"):
            self.add_line("system", data)
        elif kind == "toggle":            #from the global hotkey
            self.toggle()
        elif kind == "show":              #from the tray "Open" item
            self.show()
        elif kind == "exit" and self.on_exit:   #from the tray "Exit" item
            self.on_exit()

    def _notify_if_hidden(self, title, text):
        #at most one notification every few seconds, so a spammer can't flood your screen
        if self.is_hidden() and self.notify_callback and self._ready("notify", NOTIFY_COOLDOWN):
            self.notify_callback(title, text)

    def on_connected(self, peer_ip):
        #until the peer sends their profile, show their IP in the default colour
        self.peer_ip = peer_ip
        self.peer_name = peer_ip
        self.peer_colour = DEFAULT_PEER_COLOUR
        self.peer_profile_received = False
        self._set_status("Connected", f"{peer_ip} (encrypted)")
        self.add_line("system", f"Connected to {peer_ip}.")
        self._send_profile()

    def show_safety_code(self, code):
        #both people should see the same code. if they don't, someone in the
        #middle is decrypting and re-encrypting the chat (a man-in-the-middle attack)
        self.add_line("secure", f"Encrypted connection. Safety code: {code}")
        self.add_line("secure", "Check this matches on the other person's screen "
                                "(e.g. read it out loud). If it doesn't, disconnect.")

    def on_peer_profile(self, name, colour):
        if not self.peer_profile_received:
            self.add_line("system", f"You're chatting with {name}.")
        elif name != self.peer_name:
            self.add_line("system", f"{self.peer_name} is now called {name}.")
        self.peer_profile_received = True
        self.peer_name = name
        #each new colour makes a new icon, so a peer flipping colours nonstop
        #could eat memory. after MAX_PEER_COLOURS, new colours are ignored
        if colour in self.icon_cache or len(self.icon_cache) < MAX_PEER_COLOURS:
            self.peer_colour = colour
        self._set_status("Connected", f"{name} (encrypted)")
