"""Leased, bounded SMTP/Twilio delivery. Secrets never enter logs or outbox payloads."""

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from threading import Event
from uuid import uuid4

import httpx
from sqlalchemy import text

from apps.server.application.identity import IdentityService, row
from apps.server.application.modern_identity import AuthSettings
from apps.server.infrastructure.config import Settings
from apps.server.infrastructure.database import make_engine
from apps.server.infrastructure.migrations import is_ready
from apps.server.worker import stop_signals


def send(settings, message):
    if message['kind'] == 'email':
        mail = EmailMessage()
        mail['From'] = settings.smtp_from
        mail['To'] = message['to']
        mail['Subject'] = 'WMS — Xác minh / khôi phục tài khoản'
        mail.set_content(message['body'])
        context = ssl.create_default_context()
        cls = smtplib.SMTP if settings.smtp_starttls else smtplib.SMTP_SSL
        kwargs = dict(timeout=10)
        if not settings.smtp_starttls:
            kwargs['context'] = context
        with cls(settings.smtp_host, settings.smtp_port, **kwargs) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            smtp.send_message(mail)
    elif message['kind'] == 'sms':
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = client.post(f'https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json',
                auth=(settings.twilio_account_sid, settings.twilio_auth_token.get_secret_value()),
                data={'To': message['to'], 'From': settings.twilio_from, 'Body': message['body']})
            response.raise_for_status()
    else:
        raise ValueError('Invalid channel')


class DeliveryWorker:
    def __init__(self, identity, settings=None, sender=send):
        self.identity, self.settings, self.sender = identity, settings or AuthSettings(), sender

    def claim(self):
        now = self.identity.clock()
        with self.identity.engine.begin() as c:
            c.execute(text('''UPDATE wms.auth_delivery SET ciphertext=NULL,completed_at=:now,lease_token=NULL,lease_until=NULL
                WHERE completed_at IS NULL AND (expires_at<=:now OR attempts>=5) AND (lease_until IS NULL OR lease_until<=clock_timestamp())'''), dict(now=now))
            job = row(c, '''SELECT * FROM wms.auth_delivery WHERE completed_at IS NULL AND attempts<5
                AND expires_at>:now AND (lease_until IS NULL OR lease_until<=clock_timestamp())
                ORDER BY expires_at,id LIMIT 1 FOR UPDATE SKIP LOCKED''', now=now)
            if not job:
                return None
            user = row(c, 'SELECT id,auth_version,is_active FROM wms.app_user WHERE id=:id', id=job['user_id'])
            message = json.loads(self.identity.cipher().decrypt(job['ciphertext'].encode()))
            valid = user and user['is_active'] and user['auth_version'] == job['auth_version']
            if message.get('challenge'):
                valid = valid and row(c, 'SELECT id FROM wms.auth_contact_challenge WHERE id=:id AND consumed_at IS NULL AND expires_at>:now', id=message['challenge'], now=now)
            if message.get('contact_kind'):
                valid = valid and row(c, 'SELECT user_id FROM wms.auth_contact WHERE user_id=:id AND kind=:kind AND value=:value', id=user['id'], kind=message['contact_kind'], value=message['contact_value'])
            if message.get('reset_hash'):
                valid = valid and row(c, 'SELECT token_hash FROM wms.auth_self_reset WHERE token_hash=:hash AND consumed_at IS NULL AND expires_at>:now', hash=message['reset_hash'], now=now)
            if not valid:
                c.execute(text('UPDATE wms.auth_delivery SET completed_at=:now,ciphertext=NULL WHERE id=:id'), dict(now=now, id=job['id']))
                return {'obsolete': True}
            token = uuid4()
            c.execute(text("UPDATE wms.auth_delivery SET lease_token=:token,lease_until=clock_timestamp()+interval '90 seconds',attempts=attempts+1 WHERE id=:id"), dict(id=job['id'], token=token))
            return dict(id=job['id'], token=token, message=message)

    def run_one(self):
        job = self.claim()
        if job is None or job.get('obsolete'):
            return None if job is None else 'OBSOLETE'
        success = False
        try:
            if not self.settings.capabilities().get(job['message']['kind']):
                raise ValueError('Provider disabled')
            self.sender(self.settings, job['message'])
            success = True
        except Exception:
            pass  # Only a fixed error code may be retained; transport errors contain PII/credentials.
        finally:
            job['message'].clear()
        with self.identity.engine.begin() as c:
            c.execute(text('''UPDATE wms.auth_delivery SET
                completed_at=CASE WHEN :success THEN clock_timestamp() ELSE NULL END,
                ciphertext=CASE WHEN :success THEN NULL ELSE ciphertext END,
                lease_token=NULL,lease_until=CASE WHEN :success THEN NULL ELSE clock_timestamp()+interval '30 seconds' END,
                last_error=CASE WHEN :success THEN NULL ELSE 'DELIVERY_FAILED' END
                WHERE id=:id AND lease_token=:token AND lease_until>clock_timestamp()'''), dict(id=job['id'], token=job['token'], success=success))
        return 'SENT' if success else 'RETRY'


def main():
    os.umask(0o077)
    engine = None
    try:
        settings = Settings()
        engine = make_engine(settings)
        if not is_ready(engine):
            raise ValueError('Schema not ready')
        worker, stop = DeliveryWorker(IdentityService(engine, settings)), Event()
        with stop_signals(stop):
            while not stop.is_set():
                result = worker.run_one()
                stop.wait(5 if result is None else 1)
    except Exception:
        print('AUTH_DELIVERY_WORKER_FAILED')
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
