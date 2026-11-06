# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import secrets

from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import GitConnection, Project, State
from plane.license.utils.encryption import decrypt_data, encrypt_data
from plane.utils.git_webhooks import apply_event, parse_event, verify_signature
from plane.utils.host import base_host


class GitConnectionSerializer(serializers.ModelSerializer):
    merged_state_id = serializers.PrimaryKeyRelatedField(
        source="merged_state", queryset=State.objects.all(), required=False, allow_null=True
    )
    repository_url = serializers.CharField(max_length=2000, validators=[URLValidator(schemes=["http", "https"])])

    class Meta:
        model = GitConnection
        fields = ["id", "provider", "repository_url", "merged_state_id", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_repository_url(self, value):
        value = value.rstrip("/")
        return value[:-4] if value.endswith(".git") else value

    def validate_merged_state_id(self, state):
        if state and str(state.project_id) != str(self.context["project_id"]):
            raise serializers.ValidationError("State is not valid for this project")
        return state


def _serialize(connection, request, secret=None):
    data = GitConnectionSerializer(connection, context={"project_id": connection.project_id}).data
    path = reverse("git-webhook", kwargs={"connection_id": connection.id})
    # The API host, like the OAuth callback URLs: the web app's host may not serve /api.
    data["webhook_url"] = f"{'https' if request.is_secure() else 'http'}://{request.get_host()}{path}"
    if secret:
        data["webhook_secret"] = secret
    return data


class GitConnectionEndpoint(BaseAPIView):
    def _connection(self, slug, project_id, pk):
        return GitConnection.objects.filter(workspace__slug=slug, project_id=project_id, pk=pk).first()

    @allow_permission([ROLE.ADMIN])
    def get(self, request, slug, project_id):
        connections = GitConnection.objects.filter(workspace__slug=slug, project_id=project_id)
        return Response([_serialize(connection, request) for connection in connections], status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        serializer = GitConnectionSerializer(data=request.data, context={"project_id": project_id})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        project = Project.objects.filter(workspace__slug=slug, pk=project_id).first()
        if not project:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        # Shown once, in this response. Only the encrypted value is stored.
        secret = secrets.token_urlsafe(32)
        try:
            with transaction.atomic():
                connection = serializer.save(project=project, webhook_secret=encrypt_data(secret))
        except IntegrityError:
            return Response({"error": "This repository is already connected"}, status=status.HTTP_409_CONFLICT)
        return Response(_serialize(connection, request, secret=secret), status=status.HTTP_201_CREATED)

    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, pk):
        connection = self._connection(slug, project_id, pk)
        if not connection:
            return Response({"error": "Connection not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = GitConnectionSerializer(
            connection,
            # The repository and provider identify the webhook; to change them, connect a new one.
            data={key: request.data[key] for key in ("merged_state_id", "is_active") if key in request.data},
            partial=True,
            context={"project_id": project_id},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize(serializer.save(), request), status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, pk):
        connection = self._connection(slug, project_id, pk)
        if not connection:
            return Response({"error": "Connection not found"}, status=status.HTTP_404_NOT_FOUND)
        connection.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GitWebhookEndpoint(APIView):
    """Receives events from a Git host. The per-connection secret authenticates each request."""

    authentication_classes = []
    permission_classes = [AllowAny]
    # A busy repository sends many events from one address, and each one is checked by its signature.
    throttle_classes = []

    def post(self, request, connection_id):
        connection = (
            GitConnection.objects.filter(pk=connection_id, is_active=True, project__archived_at__isnull=True)
            .select_related("project", "merged_state")
            .first()
        )
        if not connection:
            return Response(status=status.HTTP_404_NOT_FOUND)

        body = request.body
        if not verify_signature(connection.provider, decrypt_data(connection.webhook_secret), request.headers, body):
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        try:
            payload = json.loads(body)
        except ValueError:
            return Response({"error": "Invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)

        event = parse_event(connection.provider, request.headers, payload)
        if event is None:
            return Response({"linked": 0}, status=status.HTTP_200_OK)
        linked = apply_event(connection, event, origin=base_host(request=request, is_app=True))
        return Response({"linked": linked}, status=status.HTTP_200_OK)
