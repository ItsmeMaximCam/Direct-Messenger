import getpass
import json
import os
import random

import network

#random colours on launch
STARTER_COLOURS = ["#2f6fd0", "#2e8b3e", "#c83737", "#7d4cc9", "#d07a12", "#178f8f"]


def settings_path():
    folder = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(folder, "DirectMessenger", "settings.json")


def default_settings():
    try:
        name = network.clean_name(getpass.getuser()) or "Me"
    except Exception:
        name = "Me"
    return {"name": name, "colour": random.choice(STARTER_COLOURS)}


def load_settings():
   #Read saved settings, if there's anything broken go back.
    settings = default_settings()
    try:
        with open(settings_path(), "r", encoding="utf-8") as file:
            saved = json.load(file)
    except (OSError, ValueError):
        return settings

    if not isinstance(saved, dict):
        return settings
    name = network.clean_name(str(saved.get("name", "")))
    if name:
        settings["name"] = name
    colour = str(saved.get("colour", ""))
    if network.is_colour(colour):
        settings["colour"] = colour.lower()
    return settings


def save_settings(settings):
    #write saved settings to disc
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2)
    except OSError:
        pass
