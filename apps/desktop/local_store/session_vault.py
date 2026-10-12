"""Refresh credentials live only in the OS vault; disk contains a consent marker."""
import hashlib
import json
import os
import sys
from pathlib import Path


class SessionVault:
    def __init__(self, settings, device_id):
        scope = settings.api_url.rstrip('/') + '\n' + str(device_id)
        self.account = hashlib.sha256(scope.encode()).hexdigest()
        self.service = 'InternTechLead.WMS.Session'
        self.marker = Path(settings.local_data_dir) / ('session-' + self.account + '.json')

    def backend(self):
        # Explicit native backends: never use third-party plaintext fallbacks.
        if sys.platform == 'win32':
            from keyring.backends.Windows import WinVaultKeyring
            return WinVaultKeyring()
        if sys.platform == 'darwin':
            from keyring.backends.macOS import Keyring
            return Keyring()
        from keyring.backends.SecretService import Keyring
        return Keyring()

    def mark(self, enabled):
        self.marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.marker.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'enabled': enabled}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.marker)

    def forget(self):
        # Even when a locked vault cannot delete, do not restore it next launch.
        enabled = self.marker.exists() and json.loads(self.marker.read_text()).get('enabled')
        self.mark(False)
        if not enabled:
            return
        backend = self.backend()
        if backend.get_password(self.service, self.account) is not None:
            backend.delete_password(self.service, self.account)

    def save(self, token):
        self.mark(False)
        self.backend().set_password(self.service, self.account, token)
        self.mark(True)

    def take(self):
        if not self.marker.exists() or not json.loads(self.marker.read_text()).get('enabled'):
            return None
        backend = self.backend()
        token = backend.get_password(self.service, self.account)
        # Consume before refresh: lost responses/crashes must never replay a token.
        self.mark(False)
        if token is not None:
            backend.delete_password(self.service, self.account)
        return token
