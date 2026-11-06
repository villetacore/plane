# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Generic OpenID Connect login: works with Keycloak, Authentik, Okta and other compliant providers."""

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

import jwt
import pytz
import requests

from plane.authentication.adapter.error import (
    AUTHENTICATION_ERROR_CODES,
    AuthenticationException,
)
from plane.authentication.adapter.oauth import OauthAdapter
from plane.license.utils.instance_value import get_configuration_value

REQUEST_TIMEOUT_SECONDS = 10
# Only asymmetric algorithms: accepting HS* would let the public key be used as a shared secret.
ALLOWED_ID_TOKEN_ALGORITHMS = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
DEFAULT_SCOPE = "openid email profile"
SESSION_NONCE_KEY = "oidc_nonce"
SESSION_CODE_VERIFIER_KEY = "oidc_code_verifier"


def _provider_error(message):
    return AuthenticationException(
        error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
        error_message=f"OIDC_OAUTH_PROVIDER_ERROR: {message}",
    )


def _not_configured():
    return AuthenticationException(
        error_code=AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"],
        error_message="OIDC_NOT_CONFIGURED",
    )


def _fetch_discovery_document(issuer):
    try:
        response = requests.get(f"{issuer}/.well-known/openid-configuration", timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        document = response.json()
    except (requests.RequestException, ValueError):
        raise _provider_error("Unable to fetch the discovery document")

    # OIDC Discovery 1.0 section 4.3: the issuer in the document must match the configured one.
    if not isinstance(document, dict) or document.get("issuer", "").rstrip("/") != issuer:
        raise _provider_error("Discovery document issuer does not match")
    if not all(document.get(key) for key in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
        raise _provider_error("Discovery document is incomplete")
    return document


class OIDCOAuthProvider(OauthAdapter):
    provider = "oidc"

    def __init__(self, request, code=None, state=None, callback=None):
        (issuer, client_id, client_secret, scope) = get_configuration_value(
            [
                {"key": "OIDC_ISSUER_URL", "default": os.environ.get("OIDC_ISSUER_URL")},
                {"key": "OIDC_CLIENT_ID", "default": os.environ.get("OIDC_CLIENT_ID")},
                {"key": "OIDC_CLIENT_SECRET", "default": os.environ.get("OIDC_CLIENT_SECRET")},
                {"key": "OIDC_SCOPES", "default": os.environ.get("OIDC_SCOPES", DEFAULT_SCOPE)},
            ]
        )

        if not (issuer and client_id and client_secret):
            raise _not_configured()
        if urlparse(issuer).scheme not in ("https", "http"):
            raise _not_configured()

        self.issuer = issuer.rstrip("/")
        self.discovery = _fetch_discovery_document(self.issuer)

        scope = scope or DEFAULT_SCOPE
        if "openid" not in scope.split():
            scope = f"openid {scope}"

        redirect_uri = f"{'https' if request.is_secure() else 'http'}://{request.get_host()}/auth/oidc/callback/"
        auth_url = ""
        if state:
            auth_url = self._build_auth_url(request, client_id, scope, redirect_uri, state)

        super().__init__(
            request,
            self.provider,
            client_id,
            scope,
            redirect_uri,
            auth_url,
            self.discovery["token_endpoint"],
            self.discovery.get("userinfo_endpoint"),
            client_secret,
            code,
            callback=callback,
        )

    def _build_auth_url(self, request, client_id, scope, redirect_uri, state):
        """Create the per-login nonce and PKCE verifier, kept in the session until the callback."""
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        request.session[SESSION_NONCE_KEY] = nonce
        request.session[SESSION_CODE_VERIFIER_KEY] = code_verifier
        code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
        params = {
            "client_id": client_id,
            "scope": scope,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.discovery['authorization_endpoint']}?{urlencode(params)}"

    def set_token_data(self):
        # Single use: a replayed callback finds neither value and fails.
        code_verifier = self.request.session.pop(SESSION_CODE_VERIFIER_KEY, None)
        self.expected_nonce = self.request.session.pop(SESSION_NONCE_KEY, None)
        if not code_verifier or not self.expected_nonce:
            raise _provider_error("The login session has expired")

        token_response = self.get_user_token(
            data={
                "code": self.code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        expires_in = token_response.get("expires_in")
        super().set_token_data(
            {
                "access_token": token_response.get("access_token"),
                "refresh_token": token_response.get("refresh_token"),
                "access_token_expired_at": (
                    datetime.now(tz=pytz.utc) + timedelta(seconds=int(expires_in)) if expires_in else None
                ),
                "refresh_token_expired_at": None,
                "id_token": token_response.get("id_token", ""),
            }
        )

    def _verified_id_token_claims(self):
        id_token = self.token_data.get("id_token")
        if not id_token:
            raise _provider_error("The token response has no ID token")

        supported = self.discovery.get("id_token_signing_alg_values_supported") or ["RS256"]
        algorithms = sorted(ALLOWED_ID_TOKEN_ALGORITHMS.intersection(supported))
        if not algorithms:
            raise _provider_error("The provider offers no supported signing algorithm")

        try:
            signing_key = jwt.PyJWKClient(self.discovery["jwks_uri"], timeout=REQUEST_TIMEOUT_SECONDS)
            claims = jwt.decode(
                id_token,
                signing_key.get_signing_key_from_jwt(id_token).key,
                algorithms=algorithms,
                audience=self.client_id,
                options={"require": ["exp", "iat", "sub", "iss", "aud"], "verify_iss": False},
            )
        except jwt.PyJWTError:
            raise _provider_error("ID token validation failed")

        # Compared here rather than through jwt.decode so a trailing slash in the issuer is tolerated.
        if str(claims.get("iss", "")).rstrip("/") != self.issuer:
            raise _provider_error("ID token issuer does not match")
        if not secrets.compare_digest(str(claims.get("nonce", "")).encode(), self.expected_nonce.encode()):
            raise _provider_error("ID token nonce does not match")
        return claims

    def _userinfo_claims(self, subject):
        if not self.userinfo_url:
            return {}
        try:
            response = requests.get(
                self.userinfo_url,
                headers={"Authorization": f"Bearer {self.token_data.get('access_token')}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            claims = response.json()
        except (requests.RequestException, ValueError):
            raise _provider_error("Unable to fetch user info")
        # OIDC Core 5.3.2: the UserInfo response must be for the same subject as the ID token.
        if claims.get("sub") != subject:
            raise _provider_error("User info subject does not match")
        return claims

    def set_user_data(self):
        id_claims = self._verified_id_token_claims()
        claims = {**id_claims, **self._userinfo_claims(id_claims["sub"])}

        email = claims.get("email")
        # An unverified address must not sign in to an existing account with that email (GHSA-7j95-vh8g-f365).
        if not email or claims.get("email_verified") is not True:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OAUTH_PROVIDER_UNVERIFIED_EMAIL"],
                error_message="OAUTH_PROVIDER_UNVERIFIED_EMAIL",
            )

        super().set_user_data(
            {
                "email": email,
                "user": {
                    "provider_id": str(claims["sub"]),
                    "email": email,
                    "avatar": claims.get("picture", ""),
                    "first_name": claims.get("given_name") or claims.get("name") or "",
                    "last_name": claims.get("family_name", ""),
                    "is_password_autoset": True,
                },
            }
        )
