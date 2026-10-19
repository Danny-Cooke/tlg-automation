"""Individual checks run by the monitor Lambda.

Each check is a plain function that takes an HTTP session (anything with a
`requests`-style ``get``) and returns a CheckResult. Nothing here touches AWS,
so every check is unit-testable with a fake session.

A check reports two different things:

- ``ok``: is the thing working right now.
- ``fingerprint``: a short hash of something that should stay stable. The
  handler compares it with the previous run and raises a "changed" alert when
  it moves, even if the check is still ok.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HTTP_TIMEOUT = 20

FRESHA_PARTNERS_URL = "https://partners.fresha.com/"
FRESHA_PARTNERS_CDN = "https://cdn-partners.fresha.com/assets-v2/static/js/"

# The dashboard chunk that builds the variables for the create-appointment
# mutation, and the operation names expected inside it. See
# knowledge/fresha-internal-api.md.
FRESHA_CREATE_CHUNK = "package.appointments.ViewAppointmentDrawer"
FRESHA_CREATE_OPS = ("AppointmentsManager_createAppointmentByEmployee", "availableTimeSlots")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    fingerprint: str | None = None
    info: dict = field(default_factory=dict)


def _get(http, url: str, **kw):
    headers = {"User-Agent": BROWSER_UA, **kw.pop("headers", {})}
    return http.get(url, headers=headers, timeout=HTTP_TIMEOUT, **kw)


# ---------------------------------------------------------------------------
# Our own endpoint and Meta
# ---------------------------------------------------------------------------


def check_webhook(http, webhook_url: str, verify_token: str) -> CheckResult:
    """Round-trip Meta's verification handshake through API Gateway and the bot."""
    challenge = "tlg-monitor-ping"
    params = {"hub.mode": "subscribe", "hub.verify_token": verify_token, "hub.challenge": challenge}
    try:
        resp = _get(http, webhook_url, params=params)
    except Exception as exc:  # noqa: BLE001 - any transport failure is the finding
        return CheckResult("webhook_endpoint", False, f"request failed: {exc}")
    if resp.status_code != 200 or resp.text.strip() != challenge:
        return CheckResult(
            "webhook_endpoint", False, f"expected 200 '{challenge}', got {resp.status_code} {resp.text[:80]!r}"
        )
    return CheckResult("webhook_endpoint", True, "verification handshake ok")


def check_meta_page(http, graph_base: str, page_token: str, page_id: str) -> CheckResult:
    """Page token still valid, still for our page, and the app still subscribed to messages."""
    try:
        me = _get(http, f"{graph_base}/me", params={"fields": "id,name", "access_token": page_token})
    except Exception as exc:  # noqa: BLE001
        return CheckResult("meta_page", False, f"request failed: {exc}")
    if me.status_code != 200:
        return CheckResult("meta_page", False, f"/me returned {me.status_code}: {me.text[:120]}")
    body = me.json()
    if str(body.get("id")) != str(page_id):
        return CheckResult("meta_page", False, f"token is for page {body.get('id')}, expected {page_id}")

    subs = _get(http, f"{graph_base}/{page_id}/subscribed_apps", params={"access_token": page_token})
    if subs.status_code != 200:
        return CheckResult("meta_page", False, f"subscribed_apps returned {subs.status_code}: {subs.text[:120]}")
    fields: set[str] = set()
    for app in subs.json().get("data", []):
        fields.update(app.get("subscribed_fields", []))
    if "messages" not in fields:
        return CheckResult(
            "meta_page", False, f"app is not subscribed to 'messages' on page {page_id} (fields: {sorted(fields)})"
        )
    return CheckResult(
        "meta_page",
        True,
        f"token valid for '{body.get('name')}', subscribed to {sorted(fields)}",
        fingerprint=_digest(",".join(sorted(fields))),
    )


# ---------------------------------------------------------------------------
# Fresha: the pages clients land on
# ---------------------------------------------------------------------------


def check_fresha_links(http, links: list[str], must_contain: str) -> CheckResult:
    """Every booking link the bot hands out still loads and still names the salon."""
    bad: list[str] = []
    for url in links:
        try:
            resp = _get(http, url)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{url}: {exc}")
            continue
        if resp.status_code != 200:
            bad.append(f"{url}: HTTP {resp.status_code}")
        elif must_contain and must_contain.lower() not in resp.text.lower():
            bad.append(f"{url}: loaded but does not mention '{must_contain}'")
    if bad:
        return CheckResult("fresha_links", False, "; ".join(bad))
    return CheckResult("fresha_links", True, f"{len(links)} booking links load and name the salon")


# ---------------------------------------------------------------------------
# Fresha: the partner dashboard we intend to drive
# ---------------------------------------------------------------------------

_APP_VERSION_RE = re.compile(r'APP_VERSION"\s*:\s*"([^"]+)"')
_RUNTIME_RE = re.compile(r"assets-v2/static/js/(runtime\.[0-9a-f]+\.js)")


def check_fresha_dashboard(http) -> CheckResult:
    """The dashboard shell loads and tells us its version. Info only, no fingerprint:
    Fresha ships several builds a day, so a version change is not worth an alert."""
    try:
        resp = _get(http, FRESHA_PARTNERS_URL)
    except Exception as exc:  # noqa: BLE001
        return CheckResult("fresha_dashboard", False, f"request failed: {exc}")
    if resp.status_code != 200:
        return CheckResult("fresha_dashboard", False, f"HTTP {resp.status_code}")
    version = _APP_VERSION_RE.search(resp.text)
    runtime = _RUNTIME_RE.search(resp.text)
    if not version or not runtime:
        return CheckResult("fresha_dashboard", False, "shell loaded but version or runtime bundle not found")
    return CheckResult(
        "fresha_dashboard",
        True,
        f"dashboard {version.group(1)} up",
        info={"version": version.group(1), "runtime": runtime.group(1)},
    )


def check_fresha_create_contract(http, runtime_file: str) -> CheckResult:
    """Fingerprint the code that builds the create-appointment mutation input.

    The dashboard's chunk names are stable even though their hashes change with
    every build. We follow the name to the current chunk, pull out the function
    that assembles the mutation variables, strip minifier noise and hash what is
    left. If the input shape changes, the hash changes and we get told before a
    bot booking fails.
    """
    try:
        runtime = _get(http, FRESHA_PARTNERS_CDN + runtime_file)
        if runtime.status_code != 200:
            return CheckResult("fresha_create_contract", False, f"runtime bundle HTTP {runtime.status_code}")
        chunks = parse_chunk_map(runtime.text)
        chunk_hash = chunks.get(FRESHA_CREATE_CHUNK)
        if not chunk_hash:
            return CheckResult("fresha_create_contract", False, f"chunk {FRESHA_CREATE_CHUNK} no longer in runtime map")
        chunk_file = f"async/{FRESHA_CREATE_CHUNK}.{chunk_hash}.js"
        chunk = _get(http, FRESHA_PARTNERS_CDN + chunk_file)
        if chunk.status_code != 200:
            return CheckResult("fresha_create_contract", False, f"{chunk_file} HTTP {chunk.status_code}")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("fresha_create_contract", False, f"request failed: {exc}")

    missing = [op for op in FRESHA_CREATE_OPS if op not in chunk.text]
    snippet = extract_create_builder(chunk.text)
    if missing or snippet is None:
        what = []
        if missing:
            what.append(f"operations missing: {missing}")
        if snippet is None:
            what.append("create-variables builder not found")
        return CheckResult("fresha_create_contract", False, "; ".join(what), info={"chunk": chunk_file})
    fp = _digest(normalise_js(snippet))
    return CheckResult(
        "fresha_create_contract",
        True,
        f"create mutation input shape unchanged (contract {fp})",
        fingerprint=fp,
        info={"chunk": chunk_file},
    )


_CHUNK_MAP_START = 'r.u=e=>"static/js/async/"'
_NAME_MAP_RE = re.compile(r"\(\{(.*?)\}\)\[e\]\|\|e\)", re.S)
_HASH_MAP_RE = re.compile(r'\(\{(.*?)\}\)\[e\]\+"\.js"', re.S)
_PAIR_RE = re.compile(r'(\d+):"([^"]*)"')


def parse_chunk_map(runtime_src: str) -> dict[str, str]:
    """Return {chunk name: content hash} from the rspack/webpack runtime bundle."""
    start = runtime_src.find(_CHUNK_MAP_START)
    if start < 0:
        return {}
    seg = runtime_src[start:]
    names_m = _NAME_MAP_RE.search(seg)
    if not names_m:
        return {}
    hashes_m = _HASH_MAP_RE.search(seg[names_m.end():])
    if not hashes_m:
        return {}
    names = dict(_PAIR_RE.findall(names_m.group(1)))
    hashes = dict(_PAIR_RE.findall(hashes_m.group(1)))
    return {name: hashes[cid] for cid, name in names.items() if cid in hashes}


_BUILDER_START = "let{appointmentDetails:"
_BUILDER_END_RE = re.compile(r"metadata:\{idempotencyKey:[A-Za-z_$]+,source:[A-Za-z_$]+\}\}")


def extract_create_builder(chunk_src: str) -> str | None:
    """The minified function body that turns UI state into the mutation variables."""
    start = chunk_src.find(_BUILDER_START)
    if start < 0:
        return None
    end = _BUILDER_END_RE.search(chunk_src, start)
    if not end or end.end() - start > 4000:
        return None
    return chunk_src[start : end.end()]


_SINGLE_IDENT_RE = re.compile(r"(?<![\w$])[A-Za-z_$](?![\w$])")
_MODULE_ID_RE = re.compile(r"\b\d{3,}\b")


def normalise_js(snippet: str) -> str:
    """Strip the parts a minifier renames between builds: one-letter identifiers
    and numeric module ids. Property names and structure survive."""
    out = _SINGLE_IDENT_RE.sub("_", snippet)
    return _MODULE_ID_RE.sub("#", out)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]
