"""Web Bot Auth verification vectors (PRD 20.2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agentlens import db
from agentlens.identify.keys import KeyResolver, jwk_thumbprint
from agentlens.identify.signatures import (
    EXPIRED,
    FETCH_FAILED,
    INVALID_SIG,
    TAG_IGNORED,
    UNKNOWN_KEY,
    VALID,
    RequestContext,
    SFError,
    parse_dictionary,
    parse_signature_agent,
    parse_signature_inputs,
    verify_request,
)
from agentlens.synth.signer import Signer, _public_jwk
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ORIGIN = "https://agents.desithreads.test"
AUTHORITY = "desithreads.local"
CREATED = int(datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC).timestamp())
NOW = datetime(2026, 11, 1, 10, 0, 30)  # naive UTC, as stored in DuckDB


@pytest.fixture(scope="module")
def key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture()
def signer(key: Ed25519PrivateKey) -> Signer:
    return Signer(ORIGIN, key)


@pytest.fixture()
def resolver(key: Ed25519PrivateKey) -> KeyResolver:
    jwk = _public_jwk(key)
    return KeyResolver(None, offline=True, bundled={ORIGIN: [jwk]})


def _verify(headers, resolver, *, authority=AUTHORITY, ts=NOW, sig_agent=True, path="/p/x", query="a=1"):
    ctx = RequestContext("GET", authority, path, query, "https", {"signature-agent": headers.signature_agent})
    return verify_request(
        ctx, headers.signature, headers.signature_input, headers.signature_agent if sig_agent else None,
        ts=ts, keys=resolver,
    )  # fmt: skip


def test_valid_signature_is_verified(signer, resolver):
    h = signer.sign("GET", AUTHORITY, "/p/x", "a=1", CREATED)
    res = _verify(h, resolver)
    assert res.status == VALID and res.verified
    assert res.operator_origin == ORIGIN
    assert res.keyid == signer.keyid == jwk_thumbprint(_public_jwk(signer.key))


def test_expired_signature(signer, resolver):
    h = signer.sign("GET", AUTHORITY, "/p/x", "a=1", CREATED - 1000)
    assert _verify(h, resolver).status == EXPIRED


def test_tampered_authority_is_invalid_sig(signer, resolver):
    h = signer.sign("GET", AUTHORITY, "/p/x", "a=1", CREATED)
    assert _verify(h, resolver, authority="evil.example").status == INVALID_SIG


def test_signature_from_wrong_key_is_invalid_sig(signer, resolver):
    h = signer.sign("GET", AUTHORITY, "/p/x", "a=1", CREATED, mode="wrong_key")
    assert _verify(h, resolver).status == INVALID_SIG


def test_unknown_keyid(signer, resolver):
    h = signer.sign("GET", AUTHORITY, "/p/x", "a=1", CREATED, mode="unknown_key")
    assert _verify(h, resolver).status == UNKNOWN_KEY


def test_directory_unreachable_offline_without_cache(signer):
    h = signer.sign("GET", AUTHORITY, "/p/x", "a=1", CREATED)
    empty = KeyResolver(None, offline=True, bundled={})
    res = _verify(h, empty)
    assert res.status == FETCH_FAILED and not res.verified


def test_directory_unreachable_online_falls_back_to_cache(signer, key):
    def boom(url: str):
        raise ConnectionError("no route")

    con = db.connect(":memory:")
    h = signer.sign("GET", AUTHORITY, "/p/x", "a=1", CREATED)
    assert _verify(h, KeyResolver(con, fetcher=boom, bundled={})).status == FETCH_FAILED
    con.execute("DELETE FROM key_cache")
    ok = KeyResolver(con, fetcher=lambda url: {"keys": [_public_jwk(key)]}, bundled={})
    assert _verify(h, ok).status == VALID
    # later outage: the stale cache entry still verifies
    stale = KeyResolver(con, ttl_s=0, fetcher=boom, bundled={})
    assert _verify(h, stale).status == VALID


def test_fetch_uses_well_known_directory_url(signer, key):
    seen: list[str] = []

    def fetch(url: str):
        seen.append(url)
        return {"keys": [_public_jwk(key)]}

    h = signer.sign("GET", AUTHORITY, "/p/x", "a=1", CREATED)
    assert _verify(h, KeyResolver(None, fetcher=fetch, bundled={})).status == VALID
    assert seen == [ORIGIN + "/.well-known/http-message-signatures-directory"]


def test_other_tag_is_ignored(signer, resolver):
    h = signer.sign("GET", AUTHORITY, "/p/x", "a=1", CREATED)
    h.signature_input = h.signature_input.replace('tag="web-bot-auth"', 'tag="something-else"')
    res = _verify(h, resolver)
    assert res.status == TAG_IGNORED and not res.verified


def test_no_signature_material_returns_none_status(resolver):
    res = verify_request(RequestContext("GET", AUTHORITY, "/"), None, None, None, ts=NOW, keys=resolver)
    assert res.status is None


def test_malformed_signature_input_is_invalid(resolver):
    res = verify_request(RequestContext("GET", AUTHORITY, "/"), "sig1=:AAAA:", "sig1=(((", None, ts=NOW, keys=resolver)
    assert res.status == INVALID_SIG


def test_covered_components_target_uri_and_headers(key, resolver):
    # hand-built base proves the verifier follows RFC 9421 for @method/@target-uri/@path/arbitrary headers
    import base64

    params = (
        f'("@method" "@target-uri" "@path" "x-custom");created={CREATED};expires={CREATED + 300};'
        f'keyid="{jwk_thumbprint(_public_jwk(key))}";alg="ed25519";tag="web-bot-auth"'
    )
    base = "\n".join(
        [
            '"@method": GET',
            f'"@target-uri": https://{AUTHORITY}/p/x?a=1',
            '"@path": /p/x',
            '"x-custom": hello   world',
            f'"@signature-params": {params}',
        ]
    )
    sig = base64.b64encode(key.sign(base.encode())).decode()
    ctx = RequestContext("GET", AUTHORITY, "/p/x", "a=1", "https", {"x-custom": "hello   world"})
    res = verify_request(ctx, f"sig1=:{sig}:", f"sig1={params}", ORIGIN, ts=NOW, keys=resolver)
    assert res.status == VALID
    ctx_missing = RequestContext("GET", AUTHORITY, "/p/x", "a=1", "https", {})
    assert verify_request(ctx_missing, f"sig1=:{sig}:", f"sig1={params}", ORIGIN, ts=NOW, keys=resolver).status == INVALID_SIG


def test_signature_agent_forms():
    assert parse_signature_agent('sig1="https://agents.desithreads.test"') == ORIGIN
    assert parse_signature_agent('"https://Agents.DesiThreads.test/"') == ORIGIN
    assert parse_signature_agent("https://agents.desithreads.test/some/path") == ORIGIN
    assert parse_signature_agent(None) is None


def test_structured_field_parsing():
    d = parse_dictionary('a=1, b="two";q=0.5, c=?1, d=:AQID:, e=(x y)')
    assert d["a"].value == 1 and d["b"].value == "two" and d["b"].params["q"] == 0.5
    assert d["c"].value is True and d["d"].value == b"\x01\x02\x03"
    with pytest.raises(SFError):
        parse_dictionary("a=1 b=2")
    inputs = parse_signature_inputs('sig1=("@authority" "signature-agent";key="sig1");created=1;keyid="k";tag="web-bot-auth"')
    assert [c.name for c in inputs[0].components] == ["@authority", "signature-agent"]
    assert inputs[0].tag == "web-bot-auth" and inputs[0].created == 1
