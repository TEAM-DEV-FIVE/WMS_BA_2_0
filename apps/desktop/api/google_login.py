"""System browser OAuth with an ephemeral loopback listener; no embedded login."""

import hmac
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from apps.desktop.api.client import ApiError


def browser_flow(api, *, link=False, credentials=None, cancelled=lambda: False):
    result = {}
    state = ''

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            valid = (parsed.path == '/wms-google' and len(self.path) < 8192
                     and len(query.get('state', [])) == 1 and hmac.compare_digest(query['state'][0], state)
                     and (len(query.get('code', [])) == 1 or len(query.get('error', [])) == 1))
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'none'")
            self.end_headers()
            self.wfile.write('Bạn có thể đóng cửa sổ này và quay lại WMS.'.encode('utf-8') if valid else b'Invalid callback')
            if valid:
                result.update(query)

    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        server.timeout = .25
        # Bound accepted clients too: a stalled callback must not hang shutdown.
        original = server.get_request
        def request():
            sock, address = original()
            sock.settimeout(1)
            return sock, address
        server.get_request = request
        payload = dict(port=server.server_port, device_id=api.device_id, link=link, **(credentials or {}))
        try:
            started = api._request('POST', 'auth/google/start', body=payload, authenticated=link)
        finally:
            payload.clear()
            if credentials is not None:
                credentials.clear()
        state = started['state']
        if not webbrowser.open(started['url']):
            raise ApiError('BROWSER_UNAVAILABLE', 'Không mở được trình duyệt. Hãy kiểm tra trình duyệt mặc định.')
        deadline = time.monotonic() + 180
        while not result and time.monotonic() < deadline and not cancelled():
            server.handle_request()
        if not result or result.get('error'):
            raise ApiError('UNAUTHENTICATED', 'Đăng nhập Google đã hủy hoặc hết hạn. Hãy thử lại.')
        try:
            return api._request('POST', 'auth/google/complete', body=dict(state=state, code=result['code'][0]), authenticated=link)
        finally:
            result.clear()
