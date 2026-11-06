/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { InputField } from "@makeplane/propel/components/input-field";
import { CopyOutline, DeleteOutline } from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { Select } from "@plane/blocks/select";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TGitConnection, TGitConnectionCreated, TGitProvider } from "@plane/types";
import { copyTextToClipboard } from "@plane/utils";
// components
import { StateSelect } from "@/components/dropdowns/state/state-select";
import { SettingsBoxedControlItem } from "@/components/settings/boxed-control-item";
import { SettingsHeading } from "@/components/settings/heading";
// services
import { GitConnectionService } from "@/services/project/git-connection.service";

const gitConnectionService = new GitConnectionService();

const PROVIDERS: { value: TGitProvider; name: string }[] = [
  { value: "github", name: "GitHub" },
  { value: "gitlab", name: "GitLab" },
  { value: "gitea", name: "Gitea / Forgejo" },
];

const providerName = (provider: TGitProvider) => PROVIDERS.find((item) => item.value === provider)?.name ?? provider;

type Props = {
  workspaceSlug: string;
  projectId: string;
  projectIdentifier: string;
};

function CopyableValue({ label, value, secret = false }: { label: string; value: string; secret?: boolean }) {
  const { t } = useTranslation();
  const handleCopy = () =>
    void copyTextToClipboard(value).then(() =>
      setToast({ type: "success", title: t("project_settings.git_integration.copied") })
    );

  return (
    <div className="flex items-end gap-2">
      <div className="min-w-0 flex-1">
        <InputField
          size="md"
          orientation="vertical"
          label={label}
          readOnly
          type={secret ? "password" : "text"}
          value={value}
        />
      </div>
      <IconButton variant="secondary" size="md" icon={<CopyOutline />} aria-label={label} onClick={handleCopy} />
    </div>
  );
}

export function GitIntegrationRoot({ workspaceSlug, projectId, projectIdentifier }: Props) {
  const { t } = useTranslation();
  // states
  const [provider, setProvider] = useState<TGitProvider>("github");
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [mergedStateId, setMergedStateId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [created, setCreated] = useState<TGitConnectionCreated | null>(null);
  const [toDisconnect, setToDisconnect] = useState<TGitConnection | null>(null);
  // fetch
  const { data: connections, mutate } = useSWR(`GIT_CONNECTIONS_${projectId}`, () =>
    gitConnectionService.list(workspaceSlug, projectId)
  );

  const handleConnect = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    try {
      const connection = await gitConnectionService.create(workspaceSlug, projectId, {
        provider,
        repository_url: repositoryUrl.trim(),
        merged_state_id: mergedStateId,
      });
      setCreated(connection);
      setRepositoryUrl("");
      setMergedStateId(null);
      await mutate();
    } catch {
      setToast({ type: "error", title: t("project_settings.git_integration.connect_failed") });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStateChange = async (connection: TGitConnection, stateId: string) => {
    try {
      await gitConnectionService.update(workspaceSlug, projectId, connection.id, { merged_state_id: stateId });
      await mutate();
    } catch {
      setToast({ type: "error", title: t("project_settings.git_integration.update_failed") });
    }
  };

  const handleDisconnect = async () => {
    if (!toDisconnect) return;
    setIsSubmitting(true);
    try {
      await gitConnectionService.remove(workspaceSlug, projectId, toDisconnect.id);
      if (created?.id === toDisconnect.id) setCreated(null);
      await mutate();
    } catch {
      setToast({ type: "error", title: t("project_settings.git_integration.disconnect_failed") });
    } finally {
      setIsSubmitting(false);
      setToDisconnect(null);
    }
  };

  return (
    <section className="flex w-full flex-col gap-6">
      <SettingsHeading
        title={t("project_settings.git_integration.heading")}
        description={t("project_settings.git_integration.description", { identifier: projectIdentifier })}
      />

      {created && (
        <div className="flex flex-col gap-3 rounded-lg border border-subtle bg-layer-1 p-4" role="status">
          <h3 className="text-body-sm-medium text-primary">{t("project_settings.git_integration.setup_title")}</h3>
          <p className="text-body-xs-regular text-secondary">
            {t("project_settings.git_integration.setup_instructions")}
          </p>
          <CopyableValue label={t("project_settings.git_integration.webhook_url")} value={created.webhook_url} />
          <CopyableValue
            label={t("project_settings.git_integration.webhook_secret")}
            value={created.webhook_secret}
            secret
          />
          <div>
            <Button
              variant="secondary"
              size="sm"
              stretch="auto"
              label={t("project_settings.git_integration.done")}
              onClick={() => setCreated(null)}
            />
          </div>
        </div>
      )}

      <form onSubmit={(event) => void handleConnect(event)} className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-1.5">
            <span className="text-body-xs-medium text-secondary">{t("project_settings.git_integration.provider")}</span>
            <Select<(typeof PROVIDERS)[number]>
              getValues={() => PROVIDERS}
              value={PROVIDERS.find((item) => item.value === provider) ?? null}
              onChange={(value) => setProvider(value as TGitProvider)}
              getOptionValue={(option) => option.value}
              getOptionLabel={(option) => option.name}
              pinSelected={false}
            >
              <Select.Trigger<(typeof PROVIDERS)[number]> variant="select-md">
                {(selected) => <span className="truncate">{selected[0]?.name}</span>}
              </Select.Trigger>
            </Select>
          </div>
          <InputField
            size="md"
            orientation="vertical"
            name="repository_url"
            label={t("project_settings.git_integration.repository_url")}
            type="url"
            required
            placeholder="https://github.com/acme/web"
            value={repositoryUrl}
            onChange={(event) => setRepositoryUrl(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-body-xs-medium text-secondary">
            {t("project_settings.git_integration.merged_state")}
          </span>
          <div>
            <StateSelect
              projectId={projectId}
              value={mergedStateId}
              onChange={setMergedStateId}
              placeholder={t("project_settings.git_integration.merged_state")}
              variant="pill-md"
            />
          </div>
          <span className="text-caption-sm-regular text-tertiary">
            {t("project_settings.git_integration.merged_state_hint")}
          </span>
        </div>
        <div>
          <Button
            type="submit"
            variant="primary"
            size="md"
            stretch="auto"
            loading={isSubmitting}
            label={t("project_settings.git_integration.connect")}
          />
        </div>
      </form>

      <div className="flex flex-col gap-3">
        {connections?.length === 0 && (
          <p className="text-body-xs-regular text-tertiary">{t("project_settings.git_integration.no_connections")}</p>
        )}
        {connections?.map((connection) => (
          <SettingsBoxedControlItem
            key={connection.id}
            title={<span className="break-all">{connection.repository_url}</span>}
            description={providerName(connection.provider)}
            control={
              <div className="flex items-center gap-2">
                <StateSelect
                  projectId={projectId}
                  value={connection.merged_state_id}
                  onChange={(stateId) => void handleStateChange(connection, stateId)}
                  placeholder={t("project_settings.git_integration.merged_state")}
                  variant="pill-md"
                />
                <IconButton
                  variant="ghost"
                  size="md"
                  icon={<DeleteOutline />}
                  aria-label={t("project_settings.git_integration.disconnect")}
                  onClick={() => setToDisconnect(connection)}
                />
              </div>
            }
          />
        ))}
      </div>

      <ConfirmDialog
        isOpen={!!toDisconnect}
        isSubmitting={isSubmitting}
        handleClose={() => setToDisconnect(null)}
        handleSubmit={handleDisconnect}
        title={t("project_settings.git_integration.disconnect_title")}
        content={t("project_settings.git_integration.disconnect_message", {
          repository: toDisconnect?.repository_url ?? "",
        })}
      />
    </section>
  );
}
