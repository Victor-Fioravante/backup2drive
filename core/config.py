import os
import sys
import base64


def _xor_decrypt(encoded: str, key: str) -> str:
    """Decodifica um valor ofuscado com XOR + base64."""
    raw = base64.b64decode(encoded)
    key_bytes = key.encode()
    decrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(raw))
    return decrypted.decode()


# Chave de ofuscação — substitua pela sua
_K = "YOUR_XOR_KEY_HERE"

# Valores ofuscados (gerados por tools/encode_secrets.py)
# Gere os seus com: python tools/encode_secrets.py
_ENC_MITTE_AUTH_KEY = "PLACEHOLDER"
_ENC_MITTE_SECRET = "PLACEHOLDER"
_ENC_ROOT_FOLDER = "PLACEHOLDER"


def _get(key: str, enc_value: str) -> str:
    if getattr(sys, 'frozen', False):
        return _xor_decrypt(enc_value, _K)
    # Em dev, prioriza variável de ambiente
    return os.getenv(key, _xor_decrypt(enc_value, _K))


MITTE_AUTH_KEY = _get('MITTE_AUTH_KEY', _ENC_MITTE_AUTH_KEY)
MITTE_SECRET = _get('MITTE_SECRET', _ENC_MITTE_SECRET)
ROOT_FOLDER = _get('ROOT_FOLDER', _ENC_ROOT_FOLDER)
