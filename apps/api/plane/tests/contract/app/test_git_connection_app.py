# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from rest_framework import status

from plane.db.models import GitConnection, Issue, IssueLink, Project, ProjectMember, State, WorkspaceMember
from plane.license.utils.encryption import decrypt_data, encrypt_data

SECRET = "webhook-secret"


@pytest.fixture(autouse=True)
def silence_activity():
    with patch("plane.utils.git_webhooks.issue_activity") as mocked:
        yield mocked


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Web", identifier="WEB", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def done_state(project):
    return State.objects.create(name="Done", group="completed", project=project, workspace=project.workspace)


@pytest.fixture
def issue(project):
    started = State.objects.create(name="Doing", group="started", project=project, workspace=project.workspace)
    return Issue.objects.create(name="Login", project=project, workspace=project.workspace, state=started)


def _connection(project, provider, merged_state=None):
    return GitConnection.objects.create(
        project=project,
        provider=provider,
        repository_url="https://git.example.com/acme/web",
        webhook_secret=encrypt_data(SECRET),
        merged_state=merged_state,
    )


def _headers(provider, event, body, secret=SECRET):
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if provider == "github":
        return {"HTTP_X_GITHUB_EVENT": event, "HTTP_X_HUB_SIGNATURE_256": f"sha256={digest}"}
    if provider == "gitea":
        return {"HTTP_X_GITEA_EVENT": event, "HTTP_X_GITEA_SIGNATURE": digest}
    return {"HTTP_X_GITLAB_EVENT": event, "HTTP_X_GITLAB_TOKEN": secret}


def _send(api_client, connection, event, payload, secret=SECRET):
    body = json.dumps(payload).encode()
    return api_client.post(
        f"/api/integrations/git/{connection.id}/webhook/",
        data=body,
        content_type="application/json",
        **_headers(connection.provider, event, body, secret),
    )


def _github_pull_request(issue_key, action="opened", merged=False):
    return {
        "action": action,
        "number": 7,
        "pull_request": {
            "number": 7,
            "title": f"{issue_key} fix login",
            "html_url": "https://git.example.com/acme/web/pull/7",
            "body": "",
            "merged": merged,
            "state": "closed" if merged else "open",
            "head": {"ref": "feature"},
        },
    }


def _gitlab_merge_request(action):
    return {
        "object_attributes": {
            "iid": 7,
            "title": "Fix login",
            "url": "https://git.example.com/acme/web/-/merge_requests/7",
            "description": "",
            "source_branch": "fix/web-1-login",
            "action": action,
            "state": "merged" if action == "merge" else "opened",
        }
    }


@pytest.mark.contract
@pytest.mark.django_db
class TestGitWebhook:
    @pytest.mark.parametrize(
        "provider,event,payload",
        [
            ("github", "pull_request", _github_pull_request("WEB-1")),
            ("gitea", "pull_request", _github_pull_request("WEB-1")),
            ("gitlab", "Merge Request Hook", _gitlab_merge_request("open")),
        ],
    )
    def test_pull_request_links_to_work_item(self, api_client, project, issue, provider, event, payload):
        response = _send(api_client, _connection(project, provider), event, payload)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["linked"] == 1
        assert IssueLink.objects.filter(issue=issue, metadata__kind="pull_request").count() == 1

    @pytest.mark.parametrize(
        "provider,event",
        [("github", "push"), ("gitea", "push"), ("gitlab", "Push Hook")],
    )
    def test_commit_links_to_work_item(self, api_client, project, issue, provider, event):
        payload = {
            "commits": [
                {"id": "abcdef1234", "message": "web-1: fix\n\ndetails", "url": "https://git.example.com/c/abcdef1234"}
            ]
        }
        response = _send(api_client, _connection(project, provider), event, payload)

        assert response.status_code == status.HTTP_200_OK
        link = IssueLink.objects.get(issue=issue)
        assert link.title == "abcdef1 web-1: fix"

    @pytest.mark.parametrize(
        "provider,event,payload",
        [
            ("github", "pull_request", _github_pull_request("WEB-1", action="closed", merged=True)),
            ("gitea", "pull_request", _github_pull_request("WEB-1", action="closed", merged=True)),
            ("gitlab", "Merge Request Hook", _gitlab_merge_request("merge")),
        ],
    )
    def test_merge_moves_work_item_to_configured_state(
        self, api_client, project, issue, done_state, provider, event, payload
    ):
        _send(api_client, _connection(project, provider, done_state), event, payload)

        issue.refresh_from_db()
        assert issue.state_id == done_state.id
        assert issue.completed_at is not None

    def test_closed_without_merge_keeps_state(self, api_client, project, issue, done_state):
        state_before = issue.state_id
        _send(
            api_client,
            _connection(project, "github", done_state),
            "pull_request",
            _github_pull_request("WEB-1", action="closed", merged=False),
        )
        issue.refresh_from_db()
        assert issue.state_id == state_before

    def test_merge_does_not_reopen_cancelled_work_item(self, api_client, project, issue, done_state):
        cancelled = State.objects.create(name="No", group="cancelled", project=project, workspace=project.workspace)
        Issue.objects.filter(pk=issue.pk).update(state=cancelled)
        _send(
            api_client,
            _connection(project, "github", done_state),
            "pull_request",
            _github_pull_request("WEB-1", action="closed", merged=True),
        )
        issue.refresh_from_db()
        assert issue.state_id == cancelled.id

    def test_repeated_event_keeps_one_link_and_updates_it(self, api_client, project, issue):
        connection = _connection(project, "github")
        _send(api_client, connection, "pull_request", _github_pull_request("WEB-1"))
        _send(api_client, connection, "pull_request", _github_pull_request("WEB-1", action="closed", merged=True))

        link = IssueLink.objects.get(issue=issue)
        assert link.metadata["state"] == "merged"

    @pytest.mark.parametrize("provider,event", [("github", "push"), ("gitea", "push"), ("gitlab", "Push Hook")])
    def test_wrong_secret_is_refused(self, api_client, project, issue, provider, event):
        payload = {"commits": [{"id": "abc", "message": "WEB-1", "url": "https://git.example.com/c/abc"}]}
        response = _send(api_client, _connection(project, provider), event, payload, secret="wrong")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not IssueLink.objects.filter(issue=issue).exists()

    def test_missing_signature_is_refused(self, api_client, project):
        connection = _connection(project, "github")
        response = api_client.post(
            f"/api/integrations/git/{connection.id}/webhook/",
            data=b"{}",
            content_type="application/json",
            HTTP_X_GITHUB_EVENT="push",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_key_of_another_project_is_ignored(self, api_client, project, issue, workspace):
        other = Project.objects.create(name="Other", identifier="OTH", workspace=workspace)
        other_issue = Issue.objects.create(name="x", project=other, workspace=workspace)
        payload = {
            "commits": [
                {
                    "id": "abc",
                    "message": f"OTH-{other_issue.sequence_id} and MYWEB-1",
                    "url": "https://git.example.com/c/abc",
                }
            ]
        }
        response = _send(api_client, _connection(project, "github"), "push", payload)

        assert response.data["linked"] == 0
        assert not IssueLink.objects.exists()

    def test_non_http_url_is_not_stored(self, api_client, project, issue):
        payload = {"commits": [{"id": "abc", "message": "WEB-1", "url": "javascript:alert(1)"}]}
        _send(api_client, _connection(project, "github"), "push", payload)
        assert not IssueLink.objects.exists()

    def test_inactive_connection_is_not_found(self, api_client, project):
        connection = _connection(project, "github")
        GitConnection.objects.filter(pk=connection.pk).update(is_active=False)
        response = _send(api_client, connection, "push", {"commits": []})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_other_event_types_are_ignored(self, api_client, project):
        response = _send(api_client, _connection(project, "github"), "ping", {"zen": "x"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["linked"] == 0


@pytest.mark.contract
@pytest.mark.django_db
class TestGitConnectionApi:
    def _url(self, workspace, project, pk=None):
        base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/git-connections/"
        return f"{base}{pk}/" if pk else base

    def test_create_returns_secret_once_and_stores_it_encrypted(self, session_client, workspace, project, done_state):
        response = session_client.post(
            self._url(workspace, project),
            {
                "provider": "gitlab",
                "repository_url": "https://gitlab.example.com/acme/web.git/",
                "merged_state_id": str(done_state.id),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        secret = response.data["webhook_secret"]
        assert f"/api/integrations/git/{response.data['id']}/webhook/" in response.data["webhook_url"]
        connection = GitConnection.objects.get(pk=response.data["id"])
        assert connection.repository_url == "https://gitlab.example.com/acme/web"
        assert connection.webhook_secret != secret
        assert decrypt_data(connection.webhook_secret) == secret

        listed = session_client.get(self._url(workspace, project))
        assert "webhook_secret" not in listed.data[0]

    def test_duplicate_repository_conflicts(self, session_client, workspace, project):
        body = {"provider": "github", "repository_url": "https://github.com/acme/web"}
        assert session_client.post(self._url(workspace, project), body, format="json").status_code == 201
        assert session_client.post(self._url(workspace, project), body, format="json").status_code == 409

    def test_state_of_another_project_is_rejected(self, session_client, workspace, project):
        other = Project.objects.create(name="Other", identifier="OTH", workspace=workspace)
        state = State.objects.create(name="X", group="completed", project=other, workspace=workspace)
        response = session_client.post(
            self._url(workspace, project),
            {"provider": "github", "repository_url": "https://github.com/a/b", "merged_state_id": str(state.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("url", ["javascript:alert(1)", "not a url", "file:///etc/passwd"])
    def test_invalid_repository_url_is_rejected(self, session_client, workspace, project, url):
        response = session_client.post(
            self._url(workspace, project), {"provider": "github", "repository_url": url}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_member_is_forbidden(self, session_client, workspace, project, create_user):
        ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
        # A workspace admin who is in the project keeps access whatever the project role is.
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
        assert session_client.get(self._url(workspace, project)).status_code == status.HTTP_403_FORBIDDEN

    def test_delete(self, session_client, workspace, project):
        connection = _connection(project, "github")
        response = session_client.delete(self._url(workspace, project, connection.id))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not GitConnection.objects.filter(pk=connection.pk).exists()

    def test_connection_of_another_project_is_not_found(self, session_client, workspace, project):
        other = Project.objects.create(name="Other", identifier="OTH", workspace=workspace)
        foreign = _connection(other, "github")
        response = session_client.delete(self._url(workspace, project, foreign.id))
        assert response.status_code == status.HTTP_404_NOT_FOUND
