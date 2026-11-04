#loading and tinting the app's pictures (user.png, heart.png, app.ico)

import os
import sys

from PIL import Image


def resource_path(filename):
    #finds a bundled file, both when running from source and inside the built app
    base_folder = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_folder, filename)


def load_png(filename, height):
    #Loads from resource folder and scales to height
    image = Image.open(resource_path(filename)).convert("RGBA")
    width = max(1, round(image.width * height / image.height))
    return image.resize((width, height), Image.LANCZOS)


def tint_image(base_image, colour):
    #tints any white png (user.png, heart.png) to colour
    #white parts become the colour, black outlines stay dark
    brightness = base_image.convert("L")         #white = 255, black outline = 0
    body = Image.new("RGBA", base_image.size, colour)
    outline = Image.new("RGBA", base_image.size, "#202020")
    tinted = Image.composite(body, outline, brightness)
    tinted.putalpha(base_image.getchannel("A"))  #keep the transparent background
    return tinted
