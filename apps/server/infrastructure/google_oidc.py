"""Authorization code + PKCE, with RS256 Google JWKS and nonce validation."""

import base64
import hmac
import json

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from apps.server.domain.errors import DomainError
from apps.server.infrastructure.credentials import token_hash


def decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def validate(token, keys, audience, nonce_hash, now):
    if not isinstance(token, str) or len(token) > 65536:
        raise ValueError('Invalid token')
    head, body, signature = token.split('.')
    header, claims = json.loads(decode(head)), json.loads(decode(body))
    if header.get('alg') != 'RS256':
        raise ValueError('Invalid algorithm')
    key = next(k for k in keys['keys'] if k.get('kid') == header.get('kid') and k.get('kty') == 'RSA')
    public = rsa.RSAPublicNumbers(int.from_bytes(decode(key['e']), 'big'), int.from_bytes(decode(key['n']), 'big')).public_key()
    public.verify(decode(signature), (head + '.' + body).encode(), padding.PKCS1v15(), hashes.SHA256())
    if (claims.get('iss') not in {'accounts.google.com', 'https://accounts.google.com'} or claims.get('aud') != audience
            or claims.get('azp', audience) != audience or type(claims.get('exp')) is not int or claims['exp'] <= now.timestamp()
            or type(claims.get('iat')) is not int or claims['iat'] > now.timestamp() + 60
            or claims.get('email_verified') is not True or not isinstance(claims.get('sub'), str)
            or not claims['sub'] or len(claims['sub']) > 255 or not isinstance(claims.get('nonce'), str)
            or not hmac.compare_digest(token_hash(claims['nonce']), nonce_hash)):
        raise ValueError('Invalid claims')
    return claims


def exchange(settings, code, verifier, redirect, nonce_hash, now):
    try:
        body = dict(code=code, client_id=settings.google_client_id, code_verifier=verifier,
                    redirect_uri=redirect, grant_type='authorization_code')
        if settings.google_client_secret:
            body['client_secret'] = settings.google_client_secret.get_secret_value()
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = client.post('https://oauth2.googleapis.com/token', data=body)
            response.raise_for_status()
            keys = client.get('https://www.googleapis.com/oauth2/v3/certs')
            keys.raise_for_status()
            return validate(response.json()['id_token'], keys.json(), settings.google_client_id, nonce_hash, now)
    except Exception:
        raise DomainError('UNAUTHENTICATED', 'Không xác minh được đăng nhập Google. Hãy bắt đầu lại.') from None
