/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TGitConnection, TGitConnectionCreated, TGitProvider } from "@plane/types";
// services
import { APIService } from "@/services/api.service";

export class GitConnectionService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private baseUrl(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/git-connections/`;
  }

  async list(workspaceSlug: string, projectId: string): Promise<TGitConnection[]> {
    return this.get(this.baseUrl(workspaceSlug, projectId))
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async create(
    workspaceSlug: string,
    projectId: string,
    data: { provider: TGitProvider; repository_url: string; merged_state_id: string | null }
  ): Promise<TGitConnectionCreated> {
    return this.post(this.baseUrl(workspaceSlug, projectId), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async update(
    workspaceSlug: string,
    projectId: string,
    connectionId: string,
    data: { merged_state_id: string | null }
  ): Promise<TGitConnection> {
    return this.patch(`${this.baseUrl(workspaceSlug, projectId)}${connectionId}/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async remove(workspaceSlug: string, projectId: string, connectionId: string): Promise<void> {
    return this.delete(`${this.baseUrl(workspaceSlug, projectId)}${connectionId}/`)
      .then(() => undefined)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
