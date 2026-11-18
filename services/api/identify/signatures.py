"""RFC 9421 HTTP Message Signatures verification for Web Bot Auth (Ed25519 only).

Implements a small RFC 8941 structured-field dictionary parser, the RFC 9421 signature base for the components
Web Bot Auth uses (@authority, @method, @path, @query, @target-uri, @scheme, @request-target and header fields,
including `signature-agent;key="..."`), and the verification flow from PRD 11.1. See ADR-006 for the draft version.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .keys import KeyResolver, jwk_thumbprint

TAG = "web-bot-auth"

VALID = "valid"
INVALID_SIG = "invalid_sig"
EXPIRED = "expired"
UNKNOWN_KEY = "unknown_key"
FETCH_FAILED = "fetch_failed"
TAG_IGNORED = "tag_ignored"
# Statuses that mean "someone presented a signature that does not check out" (a risk signal, PRD 11.1 step 7).
FORGERY_STATUSES = (INVALID_SIG, UNKNOWN_KEY)


class SFError(ValueError):
    """Structured-field parsing error."""


@dataclass
class SFMember:
    value: Any  # a bare value, or list[SFItem] for an inner list
    params: dict[str, Any]
    raw: str  # original text of the member value including its parameters


@dataclass
class SFItem:
    value: Any
    params: dict[str, Any]
    raw: str


_TOKEN_CHARS = re.compile(r"[A-Za-z0-9!#$%&'*+\-.^_`|~:/]")


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _parse_string(s: str, i: int) -> tuple[str, int]:
    assert s[i] == '"'
    i += 1
    out: list[str] = []
    while i < len(s):
        c = s[i]
        if c == "\\":
            if i + 1 >= len(s) or s[i + 1] not in '"\\':
                raise SFError("bad escape")
            out.append(s[i + 1])
            i += 2
        elif c == '"':
            return "".join(out), i + 1
        else:
            out.append(c)
            i += 1
    raise SFError("unterminated string")


def _parse_bare_item(s: str, i: int) -> tuple[Any, int]:
    if i >= len(s):
        raise SFError("unexpected end")
    c = s[i]
    if c == '"':
        return _parse_string(s, i)
    if c == ":":
        j = s.find(":", i + 1)
        if j < 0:
            raise SFError("unterminated byte sequence")
        try:
            return base64.b64decode(s[i + 1 : j] + "=" * (-len(s[i + 1 : j]) % 4), validate=True), j + 1
        except ValueError as exc:
            raise SFError("bad base64") from exc
    if c == "?":
        if s[i : i + 2] in ("?0", "?1"):
            return s[i + 1] == "1", i + 2
        raise SFError("bad boolean")
    if c == "-" or c.isdigit():
        j = i + 1
        while j < len(s) and (s[j].isdigit() or s[j] == "."):
            j += 1
        text = s[i:j]
        try:
            return (float(text) if "." in text else int(text)), j
        except ValueError as exc:
            raise SFError("bad number") from exc
    if c.isalpha() or c == "*":
        j = i + 1
        while j < len(s) and _TOKEN_CHARS.match(s[j]):
            j += 1
        return s[i:j], j
    raise SFError(f"unexpected character {c!r}")


def _parse_key(s: str, i: int) -> tuple[str, int]:
    j = i
    while j < len(s) and (s[j].isalnum() or s[j] in "_-.*"):
        j += 1
    if j == i:
        raise SFError("empty key")
    return s[i:j], j


def _parse_params(s: str, i: int) -> tuple[dict[str, Any], int]:
    params: dict[str, Any] = {}
    while i < len(s) and s[i] == ";":
        i = _skip_ws(s, i + 1)
        key, i = _parse_key(s, i)
        if i < len(s) and s[i] == "=":
            params[key], i = _parse_bare_item(s, i + 1)
        else:
            params[key] = True
    return params, i


def _parse_item(s: str, i: int) -> tuple[SFItem, int]:
    start = i
    value, i = _parse_bare_item(s, i)
    params, i = _parse_params(s, i)
    return SFItem(value, params, s[start:i]), i


def _parse_inner_list(s: str, i: int) -> tuple[list[SFItem], int]:
    assert s[i] == "("
    i += 1
    items: list[SFItem] = []
    while True:
        i = _skip_ws(s, i)
        if i >= len(s):
            raise SFError("unterminated inner list")
        if s[i] == ")":
            return items, i + 1
        item, i = _parse_item(s, i)
        items.append(item)


def parse_dictionary(s: str) -> dict[str, SFMember]:
    """Parse an RFC 8941 dictionary (e.g. Signature-Input, Signature, Signature-Agent)."""
    out: dict[str, SFMember] = {}
    i = _skip_ws(s, 0)
    while i < len(s):
        key, i = _parse_key(s, i)
        start = i
        value: Any
        if i < len(s) and s[i] == "=":
            i += 1
            if i < len(s) and s[i] == "(":
                value, i = _parse_inner_list(s, i)
            else:
                value, i = _parse_bare_item(s, i)
        else:
            value = True
        params, i = _parse_params(s, i)
        out[key] = SFMember(value, params, s[start + 1 : i] if s[start : start + 1] == "=" else s[start:i])
        i = _skip_ws(s, i)
        if i < len(s):
            if s[i] != ",":
                raise SFError("expected comma")
            i = _skip_ws(s, i + 1)
    return out


def parse_signature_agent(raw: str | None) -> str | None:
    """Return the origin URL from a Signature-Agent value (bare URL, sf-string, or sf-dictionary member)."""
    if not raw:
        return None
    text = raw.strip()
    candidate: str | None = None
    if "=" in text and not text.lower().startswith(("http://", "https://")):
        try:
            for member in parse_dictionary(text).values():
                if isinstance(member.value, str):
                    candidate = member.value
                    break
        except SFError:
            candidate = None
    elif text.startswith('"'):
        try:
            candidate, _ = _parse_string(text, 0)
        except SFError:
            candidate = None
    else:
        candidate = text
    if not candidate:
        return None
    parts = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    if not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


@dataclass(frozen=True)
class Component:
    raw: str
    name: str
    params: dict[str, Any]


@dataclass
class SignatureInput:
    label: str
    components: list[Component]
    params_raw: str
    created: int | None
    expires: int | None
    keyid: str | None
    alg: str | None
    tag: str | None
    nonce: str | None


def parse_signature_inputs(header: str) -> list[SignatureInput]:
    out: list[SignatureInput] = []
    for label, member in parse_dictionary(header).items():
        if not isinstance(member.value, list):
            raise SFError("signature-input member must be an inner list")
        comps = [Component(it.raw, str(it.value).lower(), it.params) for it in member.value]
        p = member.params

        def as_int(v: Any) -> int | None:
            return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

        out.append(
            SignatureInput(
                label=label,
                components=comps,
                params_raw=member.raw,
                created=as_int(p.get("created")),
                expires=as_int(p.get("expires")),
                keyid=p.get("keyid") if isinstance(p.get("keyid"), str) else None,
                alg=p.get("alg") if isinstance(p.get("alg"), str) else None,
                tag=p.get("tag") if isinstance(p.get("tag"), str) else None,
                nonce=p.get("nonce") if isinstance(p.get("nonce"), str) else None,
            )
        )
    return out


@dataclass
class RequestContext:
    """The parts of a logged request an RFC 9421 base can be built from."""

    method: str
    authority: str
    path: str
    query: str = ""
    scheme: str = "https"
    headers: dict[str, str] = field(default_factory=dict)  # lower-case names


class MissingComponent(Exception):
    pass


def default_scheme(authority: str) -> str:
    host = authority.split(":")[0]
    return "http" if host in ("localhost", "127.0.0.1") else "https"


def _component_value(comp: Component, ctx: RequestContext) -> str:
    n = comp.name
    authority = ctx.authority.lower()
    path = ctx.path or "/"
    if n == "@method":
        return ctx.method.upper()
    if n == "@authority":
        return authority
    if n == "@path":
        return path
    if n == "@scheme":
        return ctx.scheme
    if n == "@query":
        return "?" + ctx.query
    if n == "@target-uri":
        return f"{ctx.scheme}://{authority}{path}" + (f"?{ctx.query}" if ctx.query else "")
    if n == "@request-target":
        return path + (f"?{ctx.query}" if ctx.query else "")
    if n.startswith("@"):
        raise MissingComponent(n)
    value = ctx.headers.get(n)
    if value is None:
        raise MissingComponent(n)
    key = comp.params.get("key")
    if isinstance(key, str):
        try:
            member = parse_dictionary(value)[key]
        except (SFError, KeyError) as exc:
            raise MissingComponent(f"{n};key={key}") from exc
        return member.raw
    return value.strip()


def build_signature_base(inp: SignatureInput, ctx: RequestContext) -> bytes:
    lines = [f"{c.raw}: {_component_value(c, ctx)}" for c in inp.components]
    lines.append(f'"@signature-params": {inp.params_raw}')
    return "\n".join(lines).encode("utf-8")


@dataclass
class VerifyResult:
    status: str | None  # None => no signature material present
    operator_origin: str | None = None
    keyid: str | None = None
    reason: str = ""

    @property
    def verified(self) -> bool:
        return self.status == VALID


def b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_request(
    ctx: RequestContext,
    signature: str | None,
    signature_input: str | None,
    signature_agent: str | None,
    *,
    ts: datetime,
    keys: KeyResolver,
    clock_skew_s: int = 60,
) -> VerifyResult:
    """Verify one logged request. `ts` is the request time recorded in the log, not wall-clock now."""
    if not signature and not signature_input:
        return VerifyResult(None)
    try:
        inputs = parse_signature_inputs(signature_input or "")
    except SFError as exc:
        return VerifyResult(INVALID_SIG, reason=f"malformed Signature-Input: {exc}")
    wba = next((i for i in inputs if i.tag == TAG), None)
    if wba is None:
        return VerifyResult(TAG_IGNORED, reason="no signature with tag web-bot-auth")
    if wba.created is None or wba.expires is None or not wba.keyid:
        return VerifyResult(INVALID_SIG, keyid=wba.keyid, reason="missing created/expires/keyid")
    if wba.alg is not None and wba.alg.lower() != "ed25519":
        return VerifyResult(INVALID_SIG, keyid=wba.keyid, reason=f"unsupported alg {wba.alg}")

    ts_utc = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
    now = ts_utc.timestamp()
    if now > wba.expires + clock_skew_s:
        return VerifyResult(EXPIRED, keyid=wba.keyid, reason="expires < request time")
    if now < wba.created - clock_skew_s:
        return VerifyResult(INVALID_SIG, keyid=wba.keyid, reason="created is in the future")

    try:
        sig_member = parse_dictionary(signature or "").get(wba.label)
    except SFError:
        sig_member = None
    if sig_member is None or not isinstance(sig_member.value, bytes):
        return VerifyResult(INVALID_SIG, keyid=wba.keyid, reason="no matching Signature member")

    origin = parse_signature_agent(signature_agent)
    key_set = keys.get_keys(origin) if origin else keys.find_by_keyid(wba.keyid)
    if key_set.status != "ok":
        return VerifyResult(FETCH_FAILED, operator_origin=origin, keyid=wba.keyid, reason=key_set.detail)
    jwk = next((k for k in key_set.keys if jwk_thumbprint(k) == wba.keyid), None)
    if jwk is None:
        return VerifyResult(UNKNOWN_KEY, operator_origin=origin, keyid=wba.keyid, reason="keyid not in directory")
    origin = origin or key_set.origin

    try:
        base = build_signature_base(wba, ctx)
        Ed25519PublicKey.from_public_bytes(b64url_decode(jwk["x"])).verify(sig_member.value, base)
    except MissingComponent as exc:
        return VerifyResult(INVALID_SIG, origin, wba.keyid, f"covered component unavailable: {exc}")
    except (InvalidSignature, KeyError, ValueError):
        return VerifyResult(INVALID_SIG, origin, wba.keyid, "signature does not verify")
    return VerifyResult(VALID, origin, wba.keyid)
