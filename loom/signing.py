import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from loom.domain import canonical


def load_private(encoded: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(encoded, validate=True))


def public_key(private: Ed25519PrivateKey) -> str:
    return base64.b64encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def sign(private: Ed25519PrivateKey, payload: dict) -> dict:
    return {"payload": payload, "signature": base64.b64encode(private.sign(canonical(payload))).decode()}


def verify(key: str, envelope: dict) -> dict:
    public = Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True))
    public.verify(base64.b64decode(envelope["signature"], validate=True), canonical(envelope["payload"]))
    return envelope["payload"]
