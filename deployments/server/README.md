# Deploying this build

Each `v*` tag builds images in GitHub Container Registry and publishes a GitHub Release with `docker-compose.yml`, `variables.env` and `install.sh`.

| Image tag    | Comes from                  |
| ------------ | --------------------------- |
| `v1.5.0-...` | that release tag            |
| `latest`     | the newest release tag      |
| `edge`       | the newest `preview` commit |

Images are built for `linux/amd64`.

## Release a version

```bash
git tag -s v1.5.0-villetacore.2 -m "v1.5.0-villetacore.2"
git push origin v1.5.0-villetacore.2
```

## Install on a server

The server needs Docker with the compose plugin. Open ports 80 and 443, and point the domain's DNS at the server.

```bash
curl -fsSL https://github.com/villetacore/plane/releases/latest/download/install.sh -o install.sh
bash install.sh --domain plane.example.com --email you@example.com
```

Leave out `--email` to serve plain HTTP. The script creates `./plane`, generates secrets into `plane/plane.env` and starts the stack. Finish setup at `/god-mode/`.

## Upgrade or roll back

Run the script from the same directory with the version you want. `plane.env` and the data volumes are kept, and migrations run on start. Migrations are not reversed by rolling back, so back up the database first.

```bash
bash install.sh --version v1.5.0-villetacore.2
```

## Keycloak and Git

- **OIDC:** God Mode → Authentication → OIDC. The callback URL is shown on that page.
- **Git:** project settings → Git. Add the webhook URL and secret to the repository, with push and pull request events on.
