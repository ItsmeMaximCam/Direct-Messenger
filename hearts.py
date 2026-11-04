#the heart button picture and the flying hearts.
#the hearts are drawn on a separate, borderless, see-through window that floats
#exactly over the chat log. moving shapes on its canvas is cheap and the chat log
#underneath never redraws, so the animation stays smooth. (earlier versions moved
#widgets over the log, which made the log redraw every frame and caused stutter)

import math
import random
import time
import tkinter as tk

from PIL import ImageTk

from images import load_png, tint_image

HEART_COUNT = 10
HEART_COLOURS = ["#ffb3c8", "#ff8fb1", "#ff4f81", "#e0245e", "#c2185b"]
HEART_SIZES = [14, 18, 23, 29]   #heights in pixels
HEART_FRAME_MS = 16              #milliseconds between animation frames
HEART_WOBBLE_SPEED = 5.0         #how fast hearts swing side to side
HEART_SWAY = 70                  #how far they swing
HEART_SEE_THROUGH_COLOUR = "#fefefe"
BUTTON_HEART_COLOUR = "#e0245e"


class Hearts:

    def __init__(self, root, line_height):
        self.root = root
        self.chat_log = None         #set by launch(), the hearts fly over it
        self.flying = []             #hearts currently on screen
        self.overlay = None          #see-through window the hearts fly on
        self.canvas = None
        self.overlay_geometry = ""
        self.last_frame = 0.0

        #makes every colour/size of heart.png once at the start.
        #scale the sizes up on high-DPI screens (16px is a normal line height)
        scale = max(1.0, line_height / 16)
        self.images = []
        for size in HEART_SIZES:
            base = load_png("heart.png", round(size * scale))
            for colour in HEART_COLOURS:
                self.images.append(ImageTk.PhotoImage(tint_image(base, colour), master=root))
        button_heart = tint_image(load_png("heart.png", round(12 * scale)), BUTTON_HEART_COLOUR)
        self.button_image = ImageTk.PhotoImage(button_heart, master=root)

    def _window_hidden(self):
        return self.root.state() in ("withdrawn", "iconic")

    def launch(self, chat_log):
        #starts a burst of hearts that float up over the chat log
        if self._window_hidden():
            return                   #nobody would see them
        self.chat_log = chat_log
        if self.overlay is None:
            self._open_overlay()

        log_width = max(chat_log.winfo_width(), 100)
        log_height = max(chat_log.winfo_height(), 100)
        animation_running = bool(self.flying)

        for _ in range(HEART_COUNT):
            #each heart starts somewhere below the log, so they arrive staggered
            x = random.uniform(0, log_width - 30)
            y = log_height + random.uniform(0, 120)
            #a random size and shade of heart.png
            item = self.canvas.create_image(x, y, anchor="nw", image=random.choice(self.images))
            self.flying.append({
                "item": item,                         #the shape on the canvas
                "y": y,
                "speed": random.uniform(80, 170),     #pixels per second, upwards
                "wobble": random.uniform(0, 6.3),     #where in the side to side swing it starts
            })

        #only one animation loop runs, it moves every heart in self.flying
        if not animation_running:
            self.last_frame = time.perf_counter()
            self._move()

    def _open_overlay(self):
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)     #no title bar or border
        overlay.transient(self.root)       #stays above (and hides with) the main window
        #windows draws every pixel of this exact colour as see-through
        overlay.attributes("-transparentcolor", HEART_SEE_THROUGH_COLOUR)
        self.canvas = tk.Canvas(overlay, bg=HEART_SEE_THROUGH_COLOUR, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.overlay = overlay
        self.overlay_geometry = ""
        self._place_overlay()

    def _place_overlay(self):
        #keeps the overlay exactly on top of the chat log (e.g. while a nudge shakes it)
        log = self.chat_log
        geometry = (f"{log.winfo_width()}x{log.winfo_height()}"
                    f"+{log.winfo_rootx()}+{log.winfo_rooty()}")
        if geometry != self.overlay_geometry:
            self.overlay.geometry(geometry)
            self.overlay_geometry = geometry
        #windows can put a borderless window *behind* the main window (and clicking
        #the main window brings it forward), so put the overlay back just above it.
        #other apps' windows still stay on top of both
        self.overlay.lift(self.root)

    def _close_overlay(self):
        self.flying.clear()
        self.overlay.destroy()
        self.overlay = None
        self.canvas = None

    def _move(self):
        if self.overlay is None:
            return
        if self._window_hidden():
            #window was hidden mid-animation, stop so hearts don't float on the desktop
            self._close_overlay()
            return
        self._place_overlay()

        #move by how much time really passed, so a late frame doesn't slow the
        #hearts down (windows timers aren't perfectly regular)
        now = time.perf_counter()
        seconds = min(now - self.last_frame, 0.1)
        self.last_frame = now

        for heart in list(self.flying):
            heart["wobble"] += HEART_WOBBLE_SPEED * seconds
            step_x = math.sin(heart["wobble"]) * HEART_SWAY * seconds   #swing side to side
            step_y = -heart["speed"] * seconds                          #float upwards
            heart["y"] += step_y
            if heart["y"] < -40:                                        #gone off the top
                self.canvas.delete(heart["item"])
                self.flying.remove(heart)
            else:
                self.canvas.move(heart["item"], step_x, step_y)

        if self.flying:
            self.root.after(HEART_FRAME_MS, self._move)
        else:
            self._close_overlay()      #no hearts left, remove the overlay window
