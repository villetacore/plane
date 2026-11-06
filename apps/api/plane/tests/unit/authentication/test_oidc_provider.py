# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from plane.authentication.adapter.error import AUTHENTICATION_ERROR_CODES, AuthenticationException
from plane.authentication.provider.oauth.oidc import OIDCOAuthProvider

ISSUER = "https://keycloak.example.com/realms/plane"
CLIENT_ID = "plane"
NONCE = "expected-nonce"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
    "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
    "userinfo_endpoint": f"{ISSUER}/protocol/openid-connect/userinfo",
    "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
    "id_token_signing_alg_values_supported": ["RS256", "HS256"],
}


def _id_token(key=SIGNING_KEY, **overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "user-1",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "nonce": NONCE,
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="RS256")


def _json_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def _request(session=None):
    request = MagicMock()
    request.is_secure.return_value = True
    request.get_host.return_value = "plane.example.com"
    request.session = session if session is not None else {}
    return request


@pytest.fixture(autouse=True)
def config():
    with patch(
        "plane.authentication.provider.oauth.oidc.get_configuration_value",
        return_value=(ISSUER, CLIENT_ID, "secret", "email profile"),
    ):
        yield


@pytest.fixture(autouse=True)
def signing_key():
    with patch("plane.authentication.provider.oauth.oidc.jwt.PyJWKClient") as client:
        client.return_value.get_signing_key_from_jwt.return_value = MagicMock(key=SIGNING_KEY.public_key())
        yield


def _authenticated_provider(id_token, userinfo=None):
    """Run the token and user steps of a callback against mocked provider endpoints."""
    session = {"oidc_nonce": NONCE, "oidc_code_verifier": "verifier"}
    userinfo = userinfo if userinfo is not None else {"sub": "user-1", "email": "a@b.co", "email_verified": True}
    with patch("plane.authentication.provider.oauth.oidc.requests.get") as get:
        get.side_effect = [_json_response(DISCOVERY), _json_response(userinfo)]
        provider = OIDCOAuthProvider(_request(session), code="code")
        with patch.object(provider, "get_user_token", return_value={"access_token": "at", "id_token": id_token}) as t:
            provider.set_token_data()
        provider.set_user_data()
    return provider, session, t


@pytest.mark.unit
class TestOIDCProvider:
    def test_auth_url_has_pkce_nonce_and_openid_scope(self):
        session = {}
        with patch("plane.authentication.provider.oauth.oidc.requests.get", return_value=_json_response(DISCOVERY)):
            provider = OIDCOAuthProvider(_request(session), state="state-1")

        url = provider.get_auth_url()
        assert url.startswith(DISCOVERY["authorization_endpoint"])
        assert "code_challenge_method=S256" in url
        assert f"nonce={session['oidc_nonce']}" in url
        assert "scope=openid+email+profile" in url
        assert "redirect_uri=https%3A%2F%2Fplane.example.com%2Fauth%2Foidc%2Fcallback%2F" in url

    def test_missing_configuration(self):
        with patch(
            "plane.authentication.provider.oauth.oidc.get_configuration_value",
            return_value=("", "", "", ""),
        ):
            with pytest.raises(AuthenticationException) as exc:
                OIDCOAuthProvider(_request(), state="s")
        assert exc.value.error_code == AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"]

    def test_discovery_issuer_mismatch_is_rejected(self):
        with patch(
            "plane.authentication.provider.oauth.oidc.requests.get",
            return_value=_json_response({**DISCOVERY, "issuer": "https://evil.example.com"}),
        ):
            with pytest.raises(AuthenticationException):
                OIDCOAuthProvider(_request(), state="s")

    def test_valid_login_sets_user_and_consumes_session_values(self):
        provider, session, token_call = _authenticated_provider(
            _id_token(),
            {
                "sub": "user-1",
                "email": "a@b.co",
                "email_verified": True,
                "given_name": "Ada",
                "family_name": "L",
            },
        )

        assert provider.user_data["email"] == "a@b.co"
        assert provider.user_data["user"]["provider_id"] == "user-1"
        assert provider.user_data["user"]["first_name"] == "Ada"
        assert token_call.call_args.kwargs["data"]["code_verifier"] == "verifier"
        assert "oidc_nonce" not in session and "oidc_code_verifier" not in session

    @pytest.mark.parametrize(
        "token_kwargs",
        [
            {"nonce": "wrong"},
            {"iss": "https://evil.example.com"},
            {"aud": "another-client"},
            {"exp": datetime(2020, 1, 1, tzinfo=timezone.utc)},
            {"key": OTHER_KEY},
        ],
        ids=["nonce", "issuer", "audience", "expired", "signature"],
    )
    def test_invalid_id_token_is_rejected(self, token_kwargs):
        with pytest.raises(AuthenticationException) as exc:
            _authenticated_provider(_id_token(**token_kwargs))
        assert exc.value.error_code == AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"]

    def test_hs256_token_is_rejected(self):
        token = jwt.encode(
            {"iss": ISSUER, "aud": CLIENT_ID, "sub": "user-1", "nonce": NONCE, "iat": 1, "exp": 9999999999},
            "shared-secret-that-is-long-enough-for-hs256",
            algorithm="HS256",
        )
        with pytest.raises(AuthenticationException):
            _authenticated_provider(token)

    @pytest.mark.parametrize(
        "userinfo",
        [
            {"sub": "user-1", "email": "a@b.co", "email_verified": False},
            {"sub": "user-1", "email": "a@b.co"},
            {"sub": "user-1", "email": "a@b.co", "email_verified": "true"},
            {"sub": "user-1", "email_verified": True},
        ],
        ids=["false", "absent", "string", "no-email"],
    )
    def test_unverified_email_is_rejected(self, userinfo):
        with pytest.raises(AuthenticationException) as exc:
            _authenticated_provider(_id_token(), userinfo)
        assert exc.value.error_code == AUTHENTICATION_ERROR_CODES["OAUTH_PROVIDER_UNVERIFIED_EMAIL"]

    def test_userinfo_for_another_subject_is_rejected(self):
        with pytest.raises(AuthenticationException):
            _authenticated_provider(_id_token(), {"sub": "other", "email": "a@b.co", "email_verified": True})

    def test_replayed_callback_without_session_values_fails(self):
        with patch("plane.authentication.provider.oauth.oidc.requests.get", return_value=_json_response(DISCOVERY)):
            provider = OIDCOAuthProvider(_request({}), code="code")
        with pytest.raises(AuthenticationException):
            provider.set_token_data()
