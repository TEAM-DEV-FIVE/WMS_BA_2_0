"""TLS health/readiness probe; no credentials, proxy inheritance or insecure switch."""

import argparse
import json
import ssl
import urllib.request
from urllib.parse import urlsplit


def probe(url, ca_file, *, timeout=5):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/api/v1"):
        raise ValueError("Use https://DNS-SAN[:port]/api/v1")
    context = ssl.create_default_context(cafile=ca_file)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    client = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context), NoRedirect()
    )
    for suffix, expected in (("health", "ok"), ("ready", "ready")):
        with client.open(url + "/" + suffix, timeout=timeout) as response:
            if response.status != 200 or json.loads(response.read(4096)).get("status") != expected:
                raise ValueError("Not ready")
    return {"tls": "verified", "health": "ok", "schema": "ready"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(probe(args.url, args.ca)))
        return 0
    except Exception:
        print('{"ready":false,"code":"TLS_OR_SERVICE_UNAVAILABLE"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
