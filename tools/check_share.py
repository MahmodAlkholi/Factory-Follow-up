"""
Check that a shared (public) URL really serves the dashboard.

    python tools/check_share.py https://xxx.trycloudflare.com
    python tools/check_share.py https://xxx.trycloudflare.com --user admin --password factory123

Verifies three things:

1. ``/login/`` answers and hands out a CSRF token.
2. ``/api/v1/health/`` answers.
3. (optional) the login actually works and the Overview page renders behind it -
   this is what catches a tunnel that is up but whose host name was never added
   to ``ALLOWED_HOSTS`` / ``CSRF_TRUSTED_ORIGINS``.
"""

import argparse
import http.cookiejar
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

CSRF_RE = re.compile(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"')


def build_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def get(opener, url):
    with opener.open(url, timeout=30) as response:
        return response.status, response.read().decode("utf-8", "replace")


def check_login_page(opener, base):
    status, html = get(opener, base + "/login/")
    token = CSRF_RE.search(html)
    print(f"  GET  /login/            -> {status}" + ("  [csrf token ok]" if token else "  [NO CSRF TOKEN]"))
    return token.group(1) if token else None


def check_health(opener, base):
    try:
        status, body = get(opener, base + "/api/v1/health/")
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read().decode("utf-8", "replace")
    print(f"  GET  /api/v1/health/    -> {status}  {body.strip()[:80]}")
    return status == 200


def check_sign_in(opener, base, user, password, token):
    payload = urllib.parse.urlencode(
        {
            "csrfmiddlewaretoken": token,
            "username": user,
            "password": password,
            "next": "/",
        }
    ).encode()
    request = urllib.request.Request(
        base + "/login/",
        data=payload,
        headers={"Referer": base + "/login/"},
    )
    try:
        with opener.open(request, timeout=30) as response:
            html = response.read().decode("utf-8", "replace")
            url = response.geturl()
    except urllib.error.HTTPError as error:
        print(f"  POST /login/            -> {error.code}  (login failed)")
        return False

    logged_in = "Sign out" in html or "sign out" in html or "/logout/" in html
    print(f"  POST /login/            -> {response.status}  [{url}]  signed in: {logged_in}")
    if logged_in:
        status, html = get(opener, base + "/")
        has_kpi = "OEE" in html or "Output" in html
        print(f"  GET  /                  -> {status}  [dashboard rendered: {has_kpi}]")
        return has_kpi
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="The public base URL, e.g. https://xxx.trycloudflare.com")
    parser.add_argument("--user", default=None, help="Also verify a real sign-in")
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    base = args.url.rstrip("/")
    print(f"Checking {base}")
    opener, _jar = build_opener()

    ok = check_login_page(opener, base) is not None
    ok = check_health(opener, base) and ok

    if args.user and args.password:
        token = CSRF_RE.search(get(opener, base + "/login/")[1]).group(1)
        ok = check_sign_in(opener, base, args.user, args.password, token) and ok

    print("RESULT:", "ok" if ok else "PROBLEM")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
