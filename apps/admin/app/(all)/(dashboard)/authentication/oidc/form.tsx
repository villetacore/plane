/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { isEmpty } from "lodash-es";
// plane internal packages
import { API_BASE_URL } from "@plane/constants";
import type { IFormattedInstanceConfiguration, TInstanceOIDCAuthenticationConfigurationKeys } from "@plane/types";
// components
import { CodeBlock } from "@/components/common/code-block";
import type { TControllerInputFormField } from "@/components/common/controller-input";
import type { TControllerSwitchFormField } from "@/components/common/controller-switch";
import type { TCopyField } from "@/components/common/copy-field";
import { OAuthProviderForm } from "@/components/authentication/oauth-provider-form";
// hooks
import { useOAuthProviderConfigForm } from "@/hooks/use-oauth-provider-config-form";

type Props = {
  config: IFormattedInstanceConfiguration;
};

type OIDCConfigFormValues = Record<TInstanceOIDCAuthenticationConfigurationKeys, string>;

const OIDC_FORM_SWITCH_FIELD: TControllerSwitchFormField<OIDCConfigFormValues> = {
  name: "ENABLE_OIDC_SYNC",
  label: "OIDC",
};

export function InstanceOIDCConfigForm(props: Props) {
  const { config } = props;
  // form data
  const {
    control,
    formState: { errors },
    onSave,
  } = useOAuthProviderConfigForm<OIDCConfigFormValues>("OIDC", {
    OIDC_PROVIDER_NAME: config["OIDC_PROVIDER_NAME"] || "Keycloak",
    OIDC_ISSUER_URL: config["OIDC_ISSUER_URL"],
    OIDC_CLIENT_ID: config["OIDC_CLIENT_ID"],
    OIDC_CLIENT_SECRET: config["OIDC_CLIENT_SECRET"],
    OIDC_SCOPES: config["OIDC_SCOPES"] || "openid email profile",
    ENABLE_OIDC_SYNC: config["ENABLE_OIDC_SYNC"] || "0",
  });

  const originURL = !isEmpty(API_BASE_URL) ? API_BASE_URL : typeof window !== "undefined" ? window.location.origin : "";

  const OIDC_FORM_FIELDS: TControllerInputFormField<OIDCConfigFormValues>[] = [
    {
      key: "OIDC_PROVIDER_NAME",
      type: "text",
      label: "Provider name",
      description: <>Shown on the login button, for example &quot;Sign in with Keycloak&quot;.</>,
      placeholder: "Keycloak",
      error: Boolean(errors.OIDC_PROVIDER_NAME),
      required: true,
    },
    {
      key: "OIDC_ISSUER_URL",
      type: "text",
      label: "Issuer URL",
      description: (
        <>
          The base URL of the provider&apos;s discovery document. For Keycloak, use{" "}
          <CodeBlock darkerShade>https://keycloak.example.com/realms/your-realm</CodeBlock>.
        </>
      ),
      placeholder: "https://keycloak.example.com/realms/your-realm",
      error: Boolean(errors.OIDC_ISSUER_URL),
      required: true,
    },
    {
      key: "OIDC_CLIENT_ID",
      type: "text",
      label: "Client ID",
      description: <>The ID of the client you created for Plane in your identity provider.</>,
      placeholder: "plane",
      error: Boolean(errors.OIDC_CLIENT_ID),
      required: true,
    },
    {
      key: "OIDC_CLIENT_SECRET",
      type: "password",
      label: "Client secret",
      description: (
        <>
          In Keycloak, turn on client authentication for the client and copy the secret from the Credentials tab. Plane
          only accepts accounts whose email the provider marks as verified.
        </>
      ),
      placeholder: "Client secret",
      error: Boolean(errors.OIDC_CLIENT_SECRET),
      required: true,
    },
    {
      key: "OIDC_SCOPES",
      type: "text",
      label: "Scopes",
      description: <>Space-separated. Plane always requests the openid scope and needs the email claim.</>,
      placeholder: "openid email profile",
      error: Boolean(errors.OIDC_SCOPES),
      required: false,
    },
  ];

  const OIDC_SERVICE_FIELD: TCopyField[] = [
    {
      key: "Callback_URI",
      label: "Callback URI",
      url: `${originURL}/auth/oidc/callback/`,
      description: (
        <>
          We will auto-generate this. Add it to the <CodeBlock darkerShade>Valid redirect URIs</CodeBlock> of the client
          in your identity provider.
        </>
      ),
    },
  ];

  return (
    <OAuthProviderForm
      providerName="OIDC"
      control={control}
      formFields={OIDC_FORM_FIELDS}
      switchField={OIDC_FORM_SWITCH_FIELD}
      onSave={onSave}
      serviceDetails={OIDC_SERVICE_FIELD}
    />
  );
}
