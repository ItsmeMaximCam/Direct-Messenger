"""
Every frame is encrypted and holds one of these:
    MSG <text>               a chat message
    INCOGNITO <text>         a chat message shown blacked out until hovered
    PROFILE <colour> <name>  who we are, e.g. "PROFILE #3a7bd5 Alex"
    TYPING                   we are typing right now
    NUDGE                    pop the other window open and shake it
    HEART                    send flying hearts

Background threads never touch the GUI. Instead they put small event tuples
into a queue, and the GUI reads that queue on the main thread:
    ("listening", text)     server socket is ready
    ("connecting", text)    an outgoing connection attempt started
    ("connected", peer)     a peer connection is now active AND encrypted
    ("secure", code)        the safety code for this conversation
    ("disconnected", text)  the peer connection ended
    ("message", text)       the peer sent a chat message
    ("incognito", text)     the peer sent an incognito chat message
    ("profile", tuple)      the peer sent (name, colour)
    ("typing", "")          the peer is typing
    ("nudge", "")           the peer nudged us
    ("heart", "")           the peer sent hearts
    ("info", text)          something worth showing in the chat log
    ("error", text)         something went wrong (shown in the chat log)
"""

import re
import socket
import threading
import time
import unicodedata

import encryption

DEFAULT_PORT = 5050
MAX_MESSAGE_BYTES = 4096          #longest allowed message text, in bytes
MAX_NAME_LENGTH = 24              #longest allowed display name, in characters
HELLO_PREFIX = b"DMSG1 "          #starts our handshake frame; the 1 is the protocol version
MESSAGE_PREFIX = b"MSG "
INCOGNITO_PREFIX = b"INCOGNITO "
PROFILE_PREFIX = "PROFILE "
BUSY_LINE = b"BUSY"
TYPING_LINE = b"TYPING"
NUDGE_LINE = b"NUDGE"
HEART_LINE = b"HEART"
#One-word lines and the GUI event each one turns into.
SIGNAL_EVENTS = {TYPING_LINE: "typing", NUDGE_LINE: "nudge", HEART_LINE: "heart"}
COLOUR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")   # e.g. "#3a7bd5"
#Longest allowed line (prefix + text). Anything bigger is rejected.
MAX_LINE_BYTES = MAX_MESSAGE_BYTES + len(INCOGNITO_PREFIX)   #longest prefix is incognito
#Longest allowed frame: the longest line plus the encryption tamper check
MAX_FRAME_BYTES = MAX_LINE_BYTES + encryption.TAG_BYTES
LENGTH_BYTES = 4                  #every frame starts with its length as 4 bytes
CONNECT_TIMEOUT = 5.0
HANDSHAKE_TIMEOUT = 5.0           #seconds the peer has to send their public key
POLL_TIMEOUT = 0.5                #how often blocking loops check if they should stop
#a normal chat sends a few messages a second at most. anyone sending more than
#this is flooding us (e.g. a hacked app trying to freeze ours), so we hang up
MAX_FRAMES_PER_SECOND = 30
#shown when the other side doesn't speak the encrypted protocol
OLD_VERSION_REASON = ("The other person's app couldn't set up an encrypted connection "
                      "(are they using an older version?). Disconnected.")


class Messenger:

    def __init__(self, event_queue, port=DEFAULT_PORT, bind_host="0.0.0.0"):
        self.event_queue = event_queue
        self.port = port
        self.bind_host = bind_host
        self.running = False
        self.server_socket = None
        self.peer_socket = None
        self.peer_name = ""
        self.connecting = False
        #the encryption keys + counters for the current peer (None until the handshake is done)
        self.channel = None
        #The lock protects peer_socket, peer_name, connecting and channel, because several threads read and change them.
        self.lock = threading.Lock()
        #only one message may be encrypted+sent at a time, so the message counter
        #order always matches the order the messages go out on the network
        self.send_lock = threading.Lock()

    #Helper methods
    def _post(self, kind, text=""):
        #sends an event to the GUI thread
        self.event_queue.put((kind, text))

    def is_connected(self):
        with self.lock:
            return self.peer_socket is not None

    def start(self):
        #start listening for incoming connections
        #returns True if the server socket was created, False if it failed
        self.running = True
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.bind((self.bind_host, self.port))
            server.listen(1)
            server.settimeout(POLL_TIMEOUT)
        except OSError as error:
            # Usually means another program (or another copy) uses the port.
            self._post("error", f"Could not listen on port {self.port}: {error}. "
                                "You can still connect to others.")
            return False

        self.server_socket = server
        threading.Thread(target=self._listen_loop, daemon=True).start()
        self._post("listening", f"Listening on port {self.port}.")
        return True

    def stop(self):
        self.running = False
        with self.lock:
            peer = self.peer_socket
            self.peer_socket = None
            self.channel = None
        if peer is not None:
            _close_socket(peer)
        if self.server_socket is not None:
            _close_socket(self.server_socket)
            self.server_socket = None


    def _listen_loop(self):
        #accept incoming connections in a background thread
        while self.running:
            try:
                client, address = self.server_socket.accept()
            except socket.timeout:
                continue          #no caller yet, check self.running again
            except OSError:
                break             #server socket was closed

            peer_name = address[0]
            with self.lock:
                busy = self.peer_socket is not None or self.connecting
                if not busy:
                    self.peer_socket = client
                    self.peer_name = peer_name

            if busy:
                _reject_connection(client)
                self._post("info", f"Rejected a connection from {peer_name} "
                                   "(already in a conversation).")
            else:
                self._start_handshake(client, peer_name)

    def connect(self, host, port):
        #start an outgoing connection to peer
        with self.lock:
            if self.peer_socket is not None or self.connecting:
                self._post("error", "Already connected or connecting. Disconnect first.")
                return
            self.connecting = True

        self._post("connecting", f"{host}:{port}")
        threading.Thread(target=self._connect_worker, args=(host, port), daemon=True).start()

    def _connect_worker(self, host, port):
        try:
            sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
        except OSError as error:
            with self.lock:
                self.connecting = False
            self._post("disconnected", f"Could not connect to {host}:{port} ({error}).")
            return

        with self.lock:
            self.connecting = False
            # Only keep the socket if the app is still running.
            keep = self.running and self.peer_socket is None
            if keep:
                self.peer_socket = sock
                self.peer_name = host

        if keep:
            self._start_handshake(sock, host)
        else:
            _close_socket(sock)

    def disconnect(self):
        with self.lock:
            sock = self.peer_socket
            self.peer_socket = None
            self.channel = None
        if sock is not None:
            _close_socket(sock)
            self._post("disconnected", "You disconnected.")

    def _start_handshake(self, sock, peer_name):
        #both sides do this as soon as they're connected: make a fresh key pair
        #for this conversation and send the public half to the peer
        sock.settimeout(POLL_TIMEOUT)
        private_key, public_key = encryption.make_key_pair()
        try:
            sock.sendall(make_frame(HELLO_PREFIX + public_key))
        except OSError:
            self._end_connection(sock, "Connection lost.")
            return
        threading.Thread(target=self._receive_loop,
                         args=(sock, peer_name, private_key, public_key), daemon=True).start()

    def _receive_loop(self, sock, peer_name, private_key, public_key):
        #receive frames from the peer until it disconnects or we stop.
        #the first frame finishes the handshake, every frame after that is an encrypted message
        buffer = b""
        channel = None
        started = time.monotonic()
        reason = "Peer disconnected."
        second_started, frames_this_second = started, 0     #for the flood limit
        while self.running:
            #don't wait forever for someone who never sends their key
            if channel is None and time.monotonic() - started > HANDSHAKE_TIMEOUT:
                reason = OLD_VERSION_REASON
                break
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                reason = "Connection lost."
                break
            if not chunk:
                break             # the peer closed the connection

            #a buffer is temporary storage for bytes that haven't been turned into complete frames yet
            buffer += chunk
            try:
                frames, buffer = split_frames(buffer)
            except ValueError:
                #the length said "huge", which our app never sends
                reason = (OLD_VERSION_REASON if channel is None
                          else "Peer sent an oversized message. Disconnected.")
                break

            #count how many frames arrived in the current second
            now = time.monotonic()
            if now - second_started >= 1.0:
                second_started, frames_this_second = now, 0
            frames_this_second += len(frames)
            if frames_this_second > MAX_FRAMES_PER_SECOND:
                reason = "Peer was sending messages too fast (flooding). Disconnected."
                break

            for frame in frames:
                if channel is None:
                    channel = self._finish_handshake(sock, frame, peer_name,
                                                     private_key, public_key)
                    if channel is None:
                        return    #handshake failed, connection already ended
                    continue
                try:
                    line = channel.decrypt(frame)
                except encryption.DecryptionError:
                    #wrong key, or someone changed/replayed/reordered the bytes on the way
                    self._end_connection(sock, "Received a message that failed its security "
                                               "check (it may have been tampered with). Disconnected.")
                    return
                self._handle_line(line)

        self._end_connection(sock, reason)

    def _finish_handshake(self, sock, frame, peer_name, private_key, public_key):
        #reads the peer's handshake frame and sets up the encryption.
        #returns the SecureChannel, or None if the connection had to end
        if frame == BUSY_LINE:
            self._end_connection(sock, "Peer is busy in another conversation.")
            return None
        if not frame.startswith(HELLO_PREFIX):
            self._end_connection(sock, OLD_VERSION_REASON)
            return None
        try:
            channel = encryption.SecureChannel(private_key, public_key,
                                               frame[len(HELLO_PREFIX):])
        except ValueError:
            #wrong size, or a "weak" key that would give a predictable shared secret
            self._end_connection(sock, "Peer sent an invalid encryption key. Disconnected.")
            return None

        with self.lock:
            if self.peer_socket is not sock:
                return None       #we disconnected while the handshake was happening
            self.channel = channel
        self._post("connected", peer_name)
        self._post("secure", channel.safety_code)
        return channel

    def _handle_line(self, line):
        #process one decrypted message from the peer
        if line in SIGNAL_EVENTS:
            self._post(SIGNAL_EVENTS[line])
            return
        if len(line) > MAX_LINE_BYTES:
            self._post("error", "Ignored an oversized message from the peer.")
            return
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            self._post("error", "Ignored a message that was not valid UTF-8.")
            return

        if text.startswith(("MSG ", "INCOGNITO ")):
            kind, body = text.split(" ", 1)
            body = clean_text(body)
            if body:              #skip messages that were only invisible characters
                self._post("message" if kind == "MSG" else "incognito", body)
        elif text.startswith(PROFILE_PREFIX):
            profile = parse_profile(text[len(PROFILE_PREFIX):])
            if profile is None:
                self._post("error", "Ignored an invalid profile from the peer.")
            else:
                self._post("profile", profile)
        else:
            self._post("error", "Ignored a malformed message from the peer.")

    def _end_connection(self, sock, reason):
        #clean up after a peer disconnects/connection is lost
        with self.lock:
            was_active = self.peer_socket is sock
            if was_active:
                self.peer_socket = None
                self.channel = None
        _close_socket(sock)
        if was_active and self.running:
            self._post("disconnected", reason)

    def send_message(self, text, incognito=False):
        data = encode_message(text, incognito)
        if data is None:
            self._post("error", f"Message is empty or longer than {MAX_MESSAGE_BYTES} bytes.")
            return False
        return self._send_line(data)

    def send_profile(self, name, colour):
        #returns True if the profile was sent, False if not connected.
        return self._send_line(encode_profile(name, colour), quiet=True)

    def send_typing(self):
        return self._send_line(TYPING_LINE, quiet=True)

    def send_nudge(self):
        return self._send_line(NUDGE_LINE)

    def send_heart(self):
        return self._send_line(HEART_LINE)

    def _send_line(self, data, quiet=False):
        #encrypt a message and send it to the peer, returns True if it was sent, False if not connected
        #purpose of this is to avoid repeating the same code in all the send_* methods
        with self.lock:
            sock = self.peer_socket
            channel = self.channel
        if sock is None or channel is None:
            if not quiet:
                self._post("error", "Not connected.")
            return False
        try:
            with self.send_lock:
                sock.sendall(make_frame(channel.encrypt(data)))
        except OSError:
            self._end_connection(sock, "Connection lost while sending.")
            return False
        return True

def encode_message(text, incognito=False):
    #turns a string into bytes to send
    encoded = clean_text(text).encode("utf-8")
    if not encoded or len(encoded) > MAX_MESSAGE_BYTES:
        return None
    prefix = INCOGNITO_PREFIX if incognito else MESSAGE_PREFIX
    return prefix + encoded


def clean_text(text):
    #turns newlines into spaces and removes invisible control characters, e.g. ones
    #that flip text backwards (a classic trick to make a name look like someone else's)
    text = text.replace("\r", " ").replace("\n", " ")
    return "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf")).strip()


def clean_name(name):
    #cleans the name and limits its length
    return clean_text(name)[:MAX_NAME_LENGTH].strip()


def is_colour(text):
    return bool(COLOUR_PATTERN.match(text))


def encode_profile(name, colour):
    #creates the profile line to send to peer
    return f"{PROFILE_PREFIX}{colour} {clean_name(name)}".encode("utf-8")


def parse_profile(text):
    #turns the profile line into (name, colour)
    parts = text.split(" ", 1)
    if len(parts) != 2:
        return None
    colour, name = parts
    name = clean_name(name)
    if not name or not is_colour(colour):
        return None
    return name, colour.lower()


def get_lan_ip():
    #finds LAN IP address
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        ip = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    if ip.startswith("0.") or ip.startswith("127."): #not a LAN address
        return None
    return ip


def make_frame(payload):
    #puts the length in front of the payload, e.g. b"HEART" -> b"\x00\x00\x00\x05HEART"
    return len(payload).to_bytes(LENGTH_BYTES, "big") + payload


def split_frames(buffer):
    #splits a bytes buffer into complete frames, returns (frames, leftover bytes).
    #the leftover is a partial frame that a later recv() will finish.
    #raises ValueError if a frame says it's bigger than we allow.
    frames = []
    while len(buffer) >= LENGTH_BYTES:
        length = int.from_bytes(buffer[:LENGTH_BYTES], "big")
        if length > MAX_FRAME_BYTES:
            raise ValueError("frame too big")
        if len(buffer) < LENGTH_BYTES + length:
            break                 #the rest of this frame hasn't arrived yet
        frames.append(buffer[LENGTH_BYTES:LENGTH_BYTES + length])
        buffer = buffer[LENGTH_BYTES + length:]
    return frames, buffer


def parse_address(address_text, default_port=DEFAULT_PORT):
#parses IP address into (host, port)
    address_text = address_text.strip()
    if not address_text:
        return None
    host, port = address_text, default_port
    if ":" in address_text:
        host, port_text = address_text.rsplit(":", 1)
        if not port_text.isdigit():
            return None
        port = int(port_text)
    if not host or not 1 <= port <= 65535:
        return None
    return host, port


def _reject_connection(client):
    try:
        client.settimeout(1.0)
        client.sendall(make_frame(BUSY_LINE))
        client.shutdown(socket.SHUT_WR)       #tell them we're done sending
        #read and throw away what they already sent (their public key). closing with
        #unread data makes windows reset the connection, and the BUSY could get lost
        while client.recv(1024):
            pass
    except OSError:
        pass                      #includes timing out after 1 second
    _close_socket(client)


def _close_socket(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass                      #already closed or never connected
    try:
        sock.close()
    except OSError:
        pass
