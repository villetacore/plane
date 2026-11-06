/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// All the app integrations that are available
export interface IAppIntegration {
  author: string;
  avatar_url: string | null;
  created_at: string;
  created_by: string | null;
  description: any;
  id: string;
  metadata: any;
  network: number;
  provider: string;
  redirect_url: string;
  title: string;
  updated_at: string;
  updated_by: string | null;
  verified: boolean;
  webhook_secret: string;
  webhook_url: string;
}

export interface IWorkspaceIntegration {
  actor: string;
  api_token: string;
  config: any;
  created_at: string;
  created_by: string;
  id: string;
  integration: string;
  integration_detail: IAppIntegration;
  metadata: any;
  updated_at: string;
  updated_by: string;
  workspace: string;
}

// slack integration
export interface ISlackIntegration {
  id: string;
  created_at: string;
  updated_at: string;
  access_token: string;
  scopes: string;
  bot_user_id: string;
  webhook_url: string;
  data: ISlackIntegrationData;
  team_id: string;
  team_name: string;
  created_by: string;
  updated_by: string;
  project: string;
  workspace: string;
  workspace_integration: string;
}

export interface ISlackIntegrationData {
  ok: boolean;
  team: {
    id: string;
    name: string;
  };
  scope: string;
  app_id: string;
  enterprise: any;
  token_type: string;
  authed_user: string;
  bot_user_id: string;
  access_token: string;
  incoming_webhook: {
    url: string;
    channel: string;
    channel_id: string;
    configuration_url: string;
  };
  is_enterprise_install: boolean;
}

export type TGitProvider = "github" | "gitlab" | "gitea";

export type TGitConnection = {
  id: string;
  provider: TGitProvider;
  repository_url: string;
  merged_state_id: string | null;
  is_active: boolean;
  created_at: string;
  webhook_url: string;
};

/** The secret is returned only by the request that creates the connection. */
export type TGitConnectionCreated = TGitConnection & {
  webhook_secret: string;
};
