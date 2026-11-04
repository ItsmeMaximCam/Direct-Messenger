# Direct Messenger

A little LAN peer-to-peer chat app I made in Python.
It connects two Windows PCs on the same network and lets them talk to each other, end-to-end encrypted (X25519 + ChaCha20-Poly1305) to make sure nobody's snooping.

No accounts, no servers, just you and your buddy's IP address.

## What does it do???

- Chat with your friends with timestamps, names, user colours and icons
- A nudge button that pops up your friend's window and shakes it, even if they've hidden it in the tray, so they actually respond to you.
- A heart button, made specifically for my girlfriend.
- Incognito messages that stay blacked out until you hover over them
- Hides in the system tray, and Ctrl+Alt+M shows/hides it
- Encrypted messages so nobody can see what you're saying

## Running it

Easiest way: grab `DirectMessenger.zip` right-click it and extract it, then open "Install.bat" in the extracted folder.

Windows WILL complain ("Windows protected your PC") because I won't pay to code-sign it... just click More info → Run anyway. I promise it's not a virus!
Make sure to tick and allow Private Networks when the firewall pops up!

Then, type your friend's IP and hit Connect! Not sure what their IP is? Tell them to click "My IP".

### Talking to yourself (same computer)

You can also talk on the same computer, which is handy for testing. You'll need Python for this one. From PowerShell in the project folder, run:

```
python -m pip install -r requirements.txt
python main.py --port 5051
```

This starts a second copy listening on port 5051. In your first copy (the installed app, or another `python main.py`), type `127.0.0.1:5051` as the Peer IP and hit Connect.


## How it works

- Background threads handle the networking and pass everything to the window through a queue, so the window never freezes
- Messages are sent as length-prefixed frames (4 bytes for the length, then the message)
- When two apps connect, they swap fresh X25519 public keys and both work out the same secret. Every message is then encrypted with ChaCha20-Poly1305, and the safety code is a hash of both public keys
- Ctrl+Alt+M uses Windows' `RegisterHotKey`, so the app only hears that one shortcut instead of watching every key you press (which is how keyloggers work)

## Limitations

- No message history stored, everything is gone when you disconnect
- Only works on your local network (i.e, no internet chat, sorry Oliver.)
- One conversation at a time
- Windows only


Made for fun 🙂
