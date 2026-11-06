#!/usr/bin/env bash
# Install or upgrade this Plane build on a server with Docker.
# Run it again with another --version to upgrade; plane.env and the data are kept.
set -euo pipefail

REPO="villetacore/plane"
INSTALL_DIR="${PLANE_DIR:-$PWD/plane}"
VERSION="latest"
DOMAIN=""
EMAIL=""
HTTP_PORT=""
HTTPS_PORT=""

usage() {
  cat <<USAGE
Usage: install.sh --domain <domain> [options]

  --domain <domain>   Address users open, e.g. plane.example.com. Required on first install.
  --email <email>     Turn on HTTPS with a Let's Encrypt certificate for the domain.
  --version <tag>     Release to run, e.g. v1.5.0-villetacore.1. Default: the latest release.
  --dir <path>        Install directory. Default: ./plane
  --http-port <port>  Published HTTP port. Default: 80
  --https-port <port> Published HTTPS port. Default: 443
USAGE
}

die() {
  echo "Error: $*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --email) EMAIL="${2:-}"; shift 2 ;;
    --version) VERSION="${2:-}"; shift 2 ;;
    --dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --http-port) HTTP_PORT="${2:-}"; shift 2 ;;
    --https-port) HTTPS_PORT="${2:-}"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

command -v curl >/dev/null || die "curl is required"
docker compose version >/dev/null 2>&1 || die "Docker with the compose plugin is required"

# These values end up in sed expressions and an env file, so only plain characters pass.
[ -z "$DOMAIN" ] || [[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "invalid domain: $DOMAIN"
[ -z "$EMAIL" ] || [[ "$EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] || die "invalid email: $EMAIL"
[ -z "$HTTP_PORT" ] || [[ "$HTTP_PORT" =~ ^[0-9]+$ ]] || die "invalid port: $HTTP_PORT"
[ -z "$HTTPS_PORT" ] || [[ "$HTTPS_PORT" =~ ^[0-9]+$ ]] || die "invalid port: $HTTPS_PORT"
[[ "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid version: $VERSION"

if [ "$VERSION" = "latest" ]; then
  # Pin the real tag, so a later restart cannot silently change the running version.
  latest_url=$(curl -fsSLo /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest")
  VERSION="${latest_url##*/}"
  [[ "$VERSION" =~ ^v[A-Za-z0-9._-]+$ ]] || die "could not find the latest release"
fi

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
ENV_FILE="plane.env"
BASE_URL="https://github.com/$REPO/releases/download/$VERSION"

curl -fsSL "$BASE_URL/docker-compose.yml" -o docker-compose.yml.new || die "release $VERSION not found"
mv docker-compose.yml.new docker-compose.yml

set_env() {
  local key="$1" value="$2"
  if grep -q "^$key=" "$ENV_FILE"; then
    sed -i.bak "s|^$key=.*|$key=$value|" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
  else
    echo "$key=$value" >>"$ENV_FILE"
  fi
}

random_secret() {
  LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c "$1" || true
}

if [ ! -f "$ENV_FILE" ]; then
  [ -n "$DOMAIN" ] || { usage >&2; die "--domain is required on first install"; }
  curl -fsSL "$BASE_URL/variables.env" -o "$ENV_FILE"
  chmod 600 "$ENV_FILE"

  postgres_password=$(random_secret 32)
  rabbitmq_password=$(random_secret 32)
  set_env SECRET_KEY "$(random_secret 64)"
  set_env LIVE_SERVER_SECRET_KEY "$(random_secret 64)"
  set_env AWS_ACCESS_KEY_ID "$(random_secret 20)"
  set_env AWS_SECRET_ACCESS_KEY "$(random_secret 40)"
  set_env POSTGRES_PASSWORD "$postgres_password"
  set_env DATABASE_URL "postgresql://plane:$postgres_password@plane-db:5432/plane"
  set_env RABBITMQ_PASSWORD "$rabbitmq_password"
  set_env AMQP_URL "amqp://plane:$rabbitmq_password@plane-mq:5672/plane"
fi

if [ -n "$DOMAIN" ]; then
  scheme="http"
  if [ -n "$EMAIL" ]; then
    scheme="https"
    set_env SITE_ADDRESS "$DOMAIN"
    set_env CERT_EMAIL "\"email $EMAIL\""
  fi
  port="${HTTP_PORT:-80}"
  origin="$scheme://$DOMAIN"
  if [ "$scheme" = "http" ] && [ "$port" != "80" ]; then
    origin="$origin:$port"
  fi
  set_env APP_DOMAIN "$DOMAIN"
  set_env WEB_URL "$origin"
  set_env CORS_ALLOWED_ORIGINS "$origin"
fi
[ -z "$HTTP_PORT" ] || set_env LISTEN_HTTP_PORT "$HTTP_PORT"
[ -z "$HTTPS_PORT" ] || set_env LISTEN_HTTPS_PORT "$HTTPS_PORT"
set_env APP_RELEASE "$VERSION"

compose() {
  docker compose -f docker-compose.yml --env-file "$ENV_FILE" -p plane "$@"
}

compose pull
compose up -d

url=$(grep '^WEB_URL=' "$ENV_FILE" | cut -d= -f2-)
echo
echo "Plane $VERSION is starting. The first start runs migrations and takes a few minutes."
echo "  App:       $url"
echo "  God Mode:  $url/god-mode/"
echo "  Files:     $INSTALL_DIR"
