"""Test-operator Web Bot Auth signer (RFC 9421 + draft-meunier-web-bot-auth-architecture-05).

The Ed25519 key is the synthetic TEST operator's: it protects nothing. If the store has not generated it yet, the same
deterministic key (sha256("agentlens-test-operator-v1") as seed, identical to apps/store/scripts/gen-test-key.mjs) is created
and written only when the files are absent.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from agentlens import settings
from agentlens.identify.keys import jwk_thumbprint
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

CONFIG_DIR = settings.REPO_ROOT / "apps" / "store" / "config"
PEM_FILE = CONFIG_DIR / "test-operator.private.pem"
JWKS_FILE = CONFIG_DIR / "test-operator-jwks.json"
SEED_PHRASE = "agentlens-test-operator-v1"


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _public_jwk(key: Ed25519PrivateKey) -> dict[str, str]:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64u(raw)}
    return {**jwk, "kid": jwk_thumbprint(jwk)}


def load_or_create_key(pem: Path = PEM_FILE, jwks: Path = JWKS_FILE) -> Ed25519PrivateKey:
    if pem.exists():
        loaded = serialization.load_pem_private_key(pem.read_bytes(), password=None)
        if isinstance(loaded, Ed25519PrivateKey):
            return loaded
        raise ValueError(f"{pem} is not an Ed25519 key")
    key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(SEED_PHRASE.encode()).digest())
    pem.parent.mkdir(parents=True, exist_ok=True)
    pem.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    if not jwks.exists():
        jwks.write_text(json.dumps({"keys": [_public_jwk(key)]}, indent=2) + "\n", encoding="utf-8")
    return key


@dataclass
class SignedHeaders:
    signature: str
    signature_input: str
    signature_agent: str

    def as_dict(self) -> dict[str, str]:
        return {
            "signature": self.signature, "signature-input": self.signature_input, "signature-agent": self.signature_agent
        }  # fmt: skip


class Signer:
    """Signs requests as the test operator. `forge` modes produce signatures that must NOT verify."""

    def __init__(self, origin: str, key: Ed25519PrivateKey | None = None, label: str = "sig1",
                 expires_s: int = 300, agent_header: str = "dictionary") -> None:  # fmt: skip
        self.origin = origin
        self.key = key or load_or_create_key()
        self.label = label
        self.expires_s = expires_s
        self.agent_header = agent_header
        self.keyid = _public_jwk(self.key)["kid"]
        self._rogue = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"agentlens-rogue-signer").digest())
        self._rogue_keyid = _public_jwk(self._rogue)["kid"]

    def agent_value(self) -> str:
        return f'{self.label}="{self.origin}"' if self.agent_header == "dictionary" else f'"{self.origin}"'

    def sign(self, method: str, authority: str, path: str, query: str, created: int, *, scheme: str = "https",
             mode: str = "valid", nonce: str | None = None) -> SignedHeaders:  # fmt: skip
        """mode: valid | wrong_key (right keyid, rogue key signs) | unknown_key (rogue keyid and key)."""
        agent = self.agent_value()
        agent_component = f'"signature-agent";key="{self.label}"' if self.agent_header == "dictionary" else '"signature-agent"'
        keyid = self._rogue_keyid if mode == "unknown_key" else self.keyid
        signer_key = self.key if mode == "valid" else self._rogue
        params = f'("@authority" {agent_component});created={created};expires={created + self.expires_s};keyid="{keyid}"'
        if nonce:
            params += f';nonce="{nonce}"'
        params += ';alg="ed25519";tag="web-bot-auth"'
        sig_agent_member = agent.split("=", 1)[1] if self.agent_header == "dictionary" else agent
        lines = [f'"@authority": {authority.lower()}', f"{agent_component}: {sig_agent_member}", f'"@signature-params": {params}']
        sig = signer_key.sign("\n".join(lines).encode())
        return SignedHeaders(
            signature=f"{self.label}=:{base64.b64encode(sig).decode()}:",
            signature_input=f"{self.label}={params}",
            signature_agent=agent,
        )
