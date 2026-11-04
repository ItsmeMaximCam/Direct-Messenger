"""
How a conversation gets secured:
    1. Key exchange (X25519): each side makes a brand new key pair and sends
       the PUBLIC half. Both sides can then work out the same shared secret,
       but someone who only sees the two public keys (e.g. Wireshark) can't.
    2. Key derivation (HKDF): the shared secret is turned into two keys,
       one for each direction of the chat.
    3. Encryption (ChaCha20-Poly1305): every message is encrypted AND gets a
       tag that proves it wasn't changed on the way. A message counter is
       used as the nonce, so each key+nonce pair is only ever used once.
    4. Safety code: a short code made from both public keys. If it matches on
       both screens, nobody is sitting in the middle of the conversation.
"""

import hashlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

PUBLIC_KEY_BYTES = 32        #an X25519 public key is always 32 bytes
TAG_BYTES = 16               #every encrypted message gets 16 extra bytes of "tamper check"
#mixed into the key derivation so these keys can't be confused with keys from any other app
KEY_LABEL = b"Direct Messenger v1 chat keys"

#lets network.py catch failed decryption without importing cryptography itself
DecryptionError = InvalidTag


def make_key_pair():
    #makes a fresh key pair for ONE conversation
    #returns (private_key, public_key_bytes). the private key never leaves this computer
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_key, public_key


def make_safety_code(public_key_a, public_key_b):
    #hashes both public keys into 20 digits, e.g. "48213 09377 51920 66438"
    #sorted so both sides get the same code no matter who connected to who
    first, second = sorted([public_key_a, public_key_b])
    digest = hashlib.sha256(b"safety code" + first + second).digest()
    number = int.from_bytes(digest[:10], "big") % 10**20
    digits = f"{number:020d}"
    return " ".join(digits[i:i + 5] for i in range(0, 20, 5))


class SecureChannel:
    #holds the keys and message counters for one encrypted conversation

    def __init__(self, my_private_key, my_public_key, their_public_key):
        #raises ValueError if their public key is broken or not 32 bytes
        if len(their_public_key) != PUBLIC_KEY_BYTES:
            raise ValueError("public key is the wrong size")
        if their_public_key == my_public_key:
            raise ValueError("peer sent back our own public key")

        #1. key exchange: my private key + their public key = shared secret.
        #they do the same with their private key + my public key and get the SAME secret.
        their_key = X25519PublicKey.from_public_bytes(their_public_key)
        shared_secret = my_private_key.exchange(their_key)

        #2. key derivation: stretch the shared secret into 64 bytes = two 32-byte keys.
        #putting both public keys in "info" ties the keys to this exact conversation.
        first, second = sorted([my_public_key, their_public_key])
        key_material = HKDF(
            algorithm=hashes.SHA256(),
            length=64,
            salt=None,
            info=KEY_LABEL + first + second,
        ).derive(shared_secret)

        #one key per direction. if both sides encrypted with the same key while
        #both counting from 0, the same key+nonce would be used twice, which breaks the encryption.
        #whoever has the "smaller" public key sends with the first half.
        if my_public_key == first:
            send_key, receive_key = key_material[:32], key_material[32:]
        else:
            send_key, receive_key = key_material[32:], key_material[:32]

        self.sender = ChaCha20Poly1305(send_key)
        self.receiver = ChaCha20Poly1305(receive_key)
        self.send_counter = 0
        self.receive_counter = 0
        self.safety_code = make_safety_code(my_public_key, their_public_key)

    def encrypt(self, plaintext):
        #3. encrypt one message. the counter is the nonce (number used once).
        #TCP keeps messages in order, so the other side can count along and the
        #counter never has to be sent.
        nonce = _counter_to_nonce(self.send_counter)
        self.send_counter += 1
        return self.sender.encrypt(nonce, plaintext, None)

    def decrypt(self, ciphertext):
        nonce = _counter_to_nonce(self.receive_counter)
        plaintext = self.receiver.decrypt(nonce, ciphertext, None)
        self.receive_counter += 1
        return plaintext


def _counter_to_nonce(counter):
    #ChaCha20-Poly1305 needs a 12-byte nonce, so write the counter as 12 bytes
    return counter.to_bytes(12, "big")
