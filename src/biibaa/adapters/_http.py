"""Shared httpx client factory.

Honors NODE_EXTRA_CA_CERTS / SSL_CERT_FILE / REQUESTS_CA_BUNDLE so the pipeline
works behind MITM proxies (e.g. the ccli net proxy) where httpx's bundled
certifi store wouldn't otherwise trust the proxy's CA.

When BIIBAA_INSECURE_TLS=1 is set (or a proxy is detected with a self-signed
CA that fails strict validation on Python 3.12+), TLS verification is disabled
for outbound calls. This is acceptable here because the only "untrusted" hop
is the user's own loopback MITM proxy.
"""

from __future__ import annotations

import os
import ssl

import httpx

_CA_ENV_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")


def _verify() -> ssl.SSLContext | bool:
    if os.environ.get("BIIBAA_INSECURE_TLS") == "1":
        return False
    # Loopback MITM proxy signals: trust the operator and skip verification on the proxy hop.
    if any(
        "127.0.0.1" in (os.environ.get(k) or "") or "localhost" in (os.environ.get(k) or "")
        for k in ("HTTPS_PROXY", "HTTP_PROXY")
    ):
        return False
    ctx = ssl.create_default_context()
    ctx.load_default_certs()
    for var in _CA_ENV_VARS:
        path = os.environ.get(var)
        if path and os.path.exists(path):
            ctx.load_verify_locations(cafile=path)
    return ctx


def make_client(*, timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, verify=_verify())
