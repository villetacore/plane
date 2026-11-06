# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import (
    Cycle,
    Issue,
    IssueAssignee,
    IssueLabel,
    Label,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.utils.error_codes import ERROR_CODES


@pytest.fixture(autouse=True)
def silence_activity():
    with patch("plane.app.views.issue.base.issue_activity") as mocked:
        yield mocked


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Bulk", identifier="BLK", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def state(project):
    return State.objects.create(name="Doing", group="started", project=project, workspace=project.workspace)


def _issue(project, **kwargs):
    return Issue.objects.create(name="Item", project=project, workspace=project.workspace, **kwargs)


def _url(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/bulk-operation-issues/"


@pytest.mark.contract
@pytest.mark.django_db
class TestBulkIssueOperations:
    def test_updates_scalar_properties(self, session_client, workspace, project, state, silence_activity):
        issues = [_issue(project), _issue(project)]

        response = session_client.post(
            _url(workspace, project),
            {
                "issue_ids": [str(i.id) for i in issues],
                "properties": {"state_id": str(state.id), "priority": "high"},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        for issue in issues:
            issue.refresh_from_db()
            assert issue.state_id == state.id
            assert issue.priority == "high"
        assert silence_activity.delay.call_count == 2

    def test_labels_and_assignees_are_added_to_existing(self, session_client, workspace, project, create_user):
        other = User.objects.create(email="other@plane.so", username="other")
        ProjectMember.objects.create(project=project, member=other, role=15, is_active=True)
        old_label = Label.objects.create(name="old", project=project, workspace=workspace)
        new_label = Label.objects.create(name="new", project=project, workspace=workspace)
        issue = _issue(project)
        IssueLabel.objects.create(issue=issue, label=old_label, project=project, workspace=workspace)
        IssueAssignee.objects.create(issue=issue, assignee=create_user, project=project, workspace=workspace)

        response = session_client.post(
            _url(workspace, project),
            {
                "issue_ids": [str(issue.id)],
                "properties": {"label_ids": [str(new_label.id)], "assignee_ids": [str(other.id)]},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert set(IssueLabel.objects.filter(issue=issue).values_list("label_id", flat=True)) == {
            old_label.id,
            new_label.id,
        }
        assert set(IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True)) == {
            create_user.id,
            other.id,
        }

    def test_start_after_existing_due_date_fails_all(self, session_client, workspace, project):
        ok_issue = _issue(project)
        bad_issue = _issue(project, target_date=date(2026, 1, 1))

        response = session_client.post(
            _url(workspace, project),
            {"issue_ids": [str(ok_issue.id), str(bad_issue.id)], "properties": {"start_date": "2026-02-01"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error_code"] == ERROR_CODES["INVALID_ISSUE_START_DATE"]
        ok_issue.refresh_from_db()
        assert ok_issue.start_date is None

    def test_issue_from_another_project_is_rejected(self, session_client, workspace, project, create_user):
        other_project = Project.objects.create(name="Other", identifier="OTH", workspace=workspace)
        foreign_issue = _issue(other_project)

        response = session_client.post(
            _url(workspace, project),
            {"issue_ids": [str(foreign_issue.id)], "properties": {"priority": "urgent"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        foreign_issue.refresh_from_db()
        assert foreign_issue.priority == "none"

    def test_state_from_another_project_is_rejected(self, session_client, workspace, project):
        other_project = Project.objects.create(name="Other", identifier="OTH", workspace=workspace)
        foreign_state = State.objects.create(name="X", group="started", project=other_project, workspace=workspace)
        issue = _issue(project)

        response = session_client.post(
            _url(workspace, project),
            {"issue_ids": [str(issue.id)], "properties": {"state_id": str(foreign_state.id)}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize(
        "body",
        [
            {"issue_ids": [], "properties": {"priority": "low"}},
            {"issue_ids": ["not-a-uuid"], "properties": {"priority": "low"}},
            {"properties": {"priority": "low"}},
        ],
    )
    def test_invalid_issue_ids(self, session_client, workspace, project, body):
        response = session_client.post(_url(workspace, project), body, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unsupported_property_is_rejected(self, session_client, workspace, project):
        issue = _issue(project)
        response = session_client.post(
            _url(workspace, project),
            {"issue_ids": [str(issue.id)], "properties": {"name": "renamed"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_guest_is_forbidden(self, session_client, workspace, project, create_user):
        ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
        # A workspace admin who is in the project keeps access whatever the project role is.
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)
        issue = _issue(project)
        response = session_client.post(
            _url(workspace, project),
            {"issue_ids": [str(issue.id)], "properties": {"priority": "low"}},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.contract
@pytest.mark.django_db
class TestWorkspaceActiveCycles:
    def test_current_view_returns_only_running_cycles(self, session_client, workspace, project, create_user):
        now = timezone.now()
        current = Cycle.objects.create(
            name="Now",
            project=project,
            workspace=workspace,
            owned_by=create_user,
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        Cycle.objects.create(
            name="Past",
            project=project,
            workspace=workspace,
            owned_by=create_user,
            start_date=now - timedelta(days=9),
            end_date=now - timedelta(days=5),
        )

        response = session_client.get(f"/api/workspaces/{workspace.slug}/cycles/", {"cycle_view": "current"})

        assert response.status_code == status.HTTP_200_OK
        assert [str(c["id"]) for c in response.data] == [str(current.id)]
        assert response.data[0]["status"] == "CURRENT"

    def test_excludes_cycles_of_projects_the_user_is_not_in(self, session_client, workspace, create_user):
        now = timezone.now()
        other_project = Project.objects.create(name="Other", identifier="OTH", workspace=workspace)
        Cycle.objects.create(
            name="Hidden",
            project=other_project,
            workspace=workspace,
            owned_by=create_user,
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )

        response = session_client.get(f"/api/workspaces/{workspace.slug}/cycles/", {"cycle_view": "current"})

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
