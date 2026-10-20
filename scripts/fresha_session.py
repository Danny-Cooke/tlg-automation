"""Refresh the Fresha dashboard session the bot books with.

Fresha's partner login has no password: a code by email, and on a browser
it has not seen before a second code by SMS (recorded 2026-10-20, see
knowledge/fresha-internal-api.md). The session cookie it sets lasts 30 days
from login and is not extended by use. So a person logs in, and this script
does the rest:

1. Opens Chrome on the Fresha login, in a browser profile of its own under
   .local/fresha-profile. That profile keeps the year-long trusted-device
   cookie, so after the first run only the emailed code is asked for.
2. Drops the old session cookie first, so the login makes a fresh 30-day one.
3. Waits while you log in. The moment the new session cookie appears it
   closes the window.
4. Proves the cookie works from plain HTTP, the way the Lambda will use it,
   with one harmless query to Fresha's API.
5. Writes it to the SSM parameter the bot reads (SecureString). The bot
   Lambda reads that parameter at run time, so no deploy is needed.

Run it weekly (a calendar reminder is enough); each run restarts the 30
days, so a missed week costs nothing. It never prints the cookie.

    pip install -r requirements-ops.txt
    python scripts/fresha_session.py            # writes to SSM
    python scripts/fresha_session.py --dry-run  # log in and verify only

Uses the default AWS profile and region eu-west-2 unless told otherwise.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
PROFILE_DIR = REPO / ".local" / "fresha-profile"  # git-ignored with the rest of .local
LOGIN_URL = "https://partners.fresha.com/calendar"
GRAPHQL = "https://partners-api-gateway.fresha.com/graphql"
SESSION_COOKIE = "fresha_partners_session"
TRUST_COOKIE = "fresha_partner_trusted_device"
CLIENT_VERSION = "2.8.12165"  # the dashboard's own, from the 2026-10-20 recording
OWNER_ID = "1453889"  # Fresha owner id (__pid), knowledge/fresha.md
DEFAULT_PARAM = "/tlg/prod/fresha/session"
# A query the dashboard runs right after login; needs the session, changes nothing.
PROBE = "query users_profileDetails { __typename profileDetails: Partners_profileDetails { __typename joinedAt location } }"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--param", default=DEFAULT_PARAM, help="SSM parameter to write")
    ap.add_argument("--region", default="eu-west-2")
    ap.add_argument("--aws-profile", default="default", help="AWS CLI profile to write with (named explicitly so stale AWS_ACCESS_KEY_ID variables are ignored)")
    ap.add_argument("--profile-dir", type=Path, default=PROFILE_DIR, help="browser profile that keeps the trusted-device cookie")
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait for the login")
    ap.add_argument("--dry-run", action="store_true", help="log in and verify, write nothing")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # the instructions must show while the window is open

    cookie = login(args.profile_dir, args.timeout)
    if cookie is None:
        print("No session cookie appeared before the timeout. Nothing written.")
        return 1
    expires = dt.datetime.fromtimestamp(cookie["expires"], dt.timezone.utc)
    print(f"Session cookie captured; Fresha says it lasts until {expires:%a %d %b %Y %H:%M} UTC ({days_left(expires)} days).")

    who = verify(cookie["value"])
    if who is None:
        print("The cookie did not work over plain HTTP. Nothing written; see the response above.")
        return 2
    print(f"Verified from plain HTTP: Fresha knows this session as the account in {who}.")

    if args.dry_run:
        print("Dry run: not writing to SSM.")
        return 0
    try:
        write_parameter(args.param, args.region, cookie["value"], expires, profile=args.aws_profile)
    except Exception as e:  # noqa: BLE001 - say what failed without a stack trace; the cookie is not in it
        print(f"Could not write to SSM with AWS profile {args.aws_profile!r} in {args.region}: {type(e).__name__}: {str(e)[:200]}")
        print("Check `aws sts get-caller-identity --profile default` works, then run this again.")
        return 3
    print(f"Written to {args.param}. The bot picks it up within five minutes. Run this again within {days_left(expires)} days.")
    return 0


def login(profile_dir: Path, timeout: int) -> dict | None:
    """Open Chrome, let the person log in, return the fresh session cookie (Playwright's dict).

    The installed Chrome is started as an ordinary window (no automation
    flags, so Fresha's reCAPTCHA sees a normal browser) with a debugging
    port, and the script only connects to read cookies. Without an installed
    Chrome it falls back to Playwright's own browser."""
    from playwright.sync_api import sync_playwright

    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        proc, ctx = _launch(p, profile_dir)
        try:
            _drop_session_cookie(ctx)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(LOGIN_URL)
            print()
            print("  >>> YOU log in now, in the Chrome window that just opened. This script does not type anything.")
            print("  >>> Email address, then the code Fresha emails you.")
            if not _has_cookie(ctx, TRUST_COOKIE):
                print("  >>> First run on this profile: Fresha will also text a code to the account's phone. Tick 'trust this device'.")
            print("  >>> Do not close the window. It closes by itself once the calendar has loaded.")
            print()
            deadline = time.monotonic() + timeout
            last_report = 0.0
            while time.monotonic() < deadline:
                try:
                    fresh = _fresh_session_cookie(ctx)
                    if fresh:
                        time.sleep(2)  # let the app finish its first calls with the new cookie
                        return fresh
                    if time.monotonic() - last_report > 15:
                        last_report = time.monotonic()
                        names = sorted({c["name"] for c in ctx.cookies(FRESHA_URLS) if "fresha" in c["name"] or "gatekeeper" in c["name"]})
                        print(f"  waiting... page: {page.url}  fresha cookies: {', '.join(names) or 'none yet'}")
                except Exception as e:  # noqa: BLE001 - Playwright's TargetClosedError and friends
                    if "closed" in str(e):
                        print("The Chrome window was closed before Fresha set a session cookie. Run again and leave the window open until it closes itself.")
                        return None
                    raise
                time.sleep(1)
            return None
        finally:
            _shutdown(proc, ctx, profile_dir)


CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
)


def _launch(p, profile_dir: Path):
    """(process or None, context). A plain Chrome window with a debugging port if Chrome
    is installed; else Playwright's Chromium (playwright install chromium)."""
    import socket
    import subprocess

    if (profile_dir / "DevToolsActivePort").exists() and _profile_in_use(profile_dir):
        sys.exit(f"A previous run of this script still has the browser open ({profile_dir}). Close that Chrome window and run again.")
    chrome = next((c for c in CHROME_PATHS if c.exists()), None)
    if chrome is None:
        print("No installed Chrome found; using Playwright's Chromium.")
        return None, p.chromium.launch_persistent_context(str(profile_dir), headless=False, viewport=None, args=["--start-maximized"])
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([
        str(chrome), f"--user-data-dir={profile_dir}", f"--remote-debugging-port={port}",
        "--no-first-run", "--no-default-browser-check", "--start-maximized", "about:blank",
    ])
    endpoint = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            browser = p.chromium.connect_over_cdp(endpoint)
            break
        except Exception:  # noqa: BLE001 - not listening yet
            if proc.poll() is not None:
                sys.exit("Chrome exited straight away. Is another Chrome already using the profile folder?")
            time.sleep(0.5)
    else:
        proc.kill()
        sys.exit("Chrome started but never opened its debugging port.")
    return proc, browser.contexts[0]


def _profile_in_use(profile_dir: Path) -> bool:
    try:
        port = int((profile_dir / "DevToolsActivePort").read_text().splitlines()[0])
    except (OSError, ValueError, IndexError):
        return False
    import socket

    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _shutdown(proc, ctx, profile_dir: Path) -> None:
    try:
        if proc is None:
            ctx.close()
        else:
            try:
                ctx.browser.close()  # disconnects
            except Exception:  # noqa: BLE001
                pass
            if sys.platform == "win32":
                # Chrome relaunches itself (de-elevation, launcher chain), so the
                # window's processes are not always under our pid. Every process
                # using this profile folder is ours; end them all.
                import subprocess

                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                subprocess.run([
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*" + str(profile_dir) + "*' } "
                    "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
                ], capture_output=True)
            else:
                proc.terminate()
            try:
                proc.wait(10)
            except Exception:  # noqa: BLE001
                proc.kill()
    except Exception:  # noqa: BLE001 - already gone
        pass


FRESHA_URLS = ["https://partners.fresha.com", "https://partners-api-gateway.fresha.com", "https://www.fresha.com"]


def _drop_session_cookie(ctx) -> None:
    """Remove the old session cookie only, so the login issues a new 30-day one
    and the trusted-device cookie survives (no SMS code next time)."""
    if not _has_cookie(ctx, SESSION_COOKIE):
        return
    try:
        ctx.clear_cookies(name=SESSION_COOKIE)
    except TypeError:  # Playwright before 1.43: no name filter; restore everything else by hand
        keep = [c for c in ctx.cookies(FRESHA_URLS) if c["name"] != SESSION_COOKIE]
        ctx.clear_cookies()
        if keep:
            ctx.add_cookies(keep)


def _has_cookie(ctx, name: str) -> bool:
    return any(c["name"] == name for c in ctx.cookies(FRESHA_URLS))


def _fresh_session_cookie(ctx) -> dict | None:
    """The session cookie, once Fresha has set it. Expiry is epoch seconds, -1 for a session cookie."""
    for c in ctx.cookies("https://partners-api-gateway.fresha.com"):
        if c["name"] == SESSION_COOKIE and c.get("value"):
            if c.get("expires", -1) > 0:
                return c
    return None


def verify(cookie_value: str, http=None) -> str | None:
    """Run the probe query with only the session cookie. Returns the profile location on success."""
    http = http or requests.Session()
    resp = http.post(
        GRAPHQL,
        params={"_query": "users_profileDetails", "_client_platform": "web", "_client_version": CLIENT_VERSION, "__pid": OWNER_ID},
        data={"operationName": "users_profileDetails", "query": PROBE, "variables": "{}"},
        cookies={SESSION_COOKIE: cookie_value},
        headers={"accept": "application/json", "origin": "https://partners.fresha.com", "referer": "https://partners.fresha.com/"},
        timeout=30,
    )
    try:
        body = resp.json()
    except ValueError:
        body = {}
    details = (body.get("data") or {}).get("profileDetails") if isinstance(body, dict) else None
    if resp.status_code == 200 and details:
        return details.get("location") or "an account with no location set"
    print(f"Probe failed: HTTP {resp.status_code}, {json.dumps(body)[:300]}")
    return None


def write_parameter(name: str, region: str, cookie_value: str, expires: dt.datetime, *, profile: str = "default") -> None:
    """Create or update the SecureString. A named profile makes boto3 skip any
    AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY left in the shell's environment."""
    import boto3

    payload = {
        "cookie": cookie_value,
        "expires_at": expires.isoformat(timespec="seconds"),
        "refreshed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    ssm = boto3.Session(profile_name=profile, region_name=region).client("ssm")
    ssm.put_parameter(Name=name, Type="SecureString", Value=json.dumps(payload), Overwrite=True)


def days_left(expires: dt.datetime) -> int:
    return max(0, (expires - dt.datetime.now(dt.timezone.utc)).days)


if __name__ == "__main__":
    sys.exit(main())
