#!/usr/bin/env bash
# One-shot provisioner for Sentinel on a fresh Ubuntu/Debian host.
#
#   bash provision.sh
#
# Idempotent: installs Docker + the Compose plugin if missing, clones (or pulls)
# the repo, creates .env from the template on first run (then STOPS so you can
# fill in your keys), and on a subsequent run builds and starts the stack and
# runs the dependency health check.
#
# Override defaults via env vars:
#   REPO_URL=...  BRANCH=...  TARGET=/opt/sentinel  bash provision.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/wj200/stock-sentiment-analysis-pipeline.git}"
BRANCH="${BRANCH:-claude/telegram-financial-alerts-pdf-tmwzcx}"
TARGET="${TARGET:-$HOME/stock-sentiment-analysis-pipeline}"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }

# Use sudo only if we're not already root.
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

# Pick a working docker invocation (with sudo if the daemon isn't reachable yet).
docker_cmd() {
  if docker info >/dev/null 2>&1; then docker "$@"; else $SUDO docker "$@"; fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker already installed ($(docker --version))"
  else
    log "Installing Docker Engine + Compose plugin"
    curl -fsSL https://get.docker.com | $SUDO sh
    if [ -n "$SUDO" ]; then
      $SUDO usermod -aG docker "$USER" || true
      warn "Added $USER to the 'docker' group. Log out/in later to drop 'sudo'."
    fi
  fi
  $SUDO systemctl enable docker >/dev/null 2>&1 || true
  # Verify the compose plugin is present.
  if ! docker_cmd compose version >/dev/null 2>&1; then
    warn "Docker Compose plugin not found. Install 'docker-compose-plugin' and re-run."
    exit 1
  fi
}

clone_or_update() {
  if [ -d "$TARGET/.git" ]; then
    log "Updating existing checkout at $TARGET"
    git -C "$TARGET" fetch origin "$BRANCH"
    git -C "$TARGET" checkout "$BRANCH"
    git -C "$TARGET" pull --ff-only origin "$BRANCH" || warn "Could not fast-forward; leaving local state."
  else
    log "Cloning $REPO_URL ($BRANCH) into $TARGET"
    git clone -b "$BRANCH" "$REPO_URL" "$TARGET"
  fi
}

ensure_env() {
  if [ ! -f "$TARGET/.env" ]; then
    cp "$TARGET/.env.example" "$TARGET/.env"
    log ".env created from template."
    warn "Edit $TARGET/.env and set at least TELEGRAM_BOT_TOKEN, then run this script again."
    exit 0
  fi
  # Fail early if the required token is still blank.
  if ! grep -qE '^TELEGRAM_BOT_TOKEN=.+' "$TARGET/.env"; then
    warn "TELEGRAM_BOT_TOKEN is empty in $TARGET/.env. Set it and re-run."
    exit 1
  fi
}

bring_up() {
  cd "$TARGET"
  log "Building and starting the stack (first build downloads torch/Spark; be patient)"
  docker_cmd compose up -d --build
  log "Waiting ~20s for services to settle, then running the health check"
  sleep 20
  docker_cmd compose run --rm telegram-bot python -m ops.health || \
    warn "Health check reported issues (Kafka may still be starting). Re-run: docker compose run --rm telegram-bot python -m ops.health --probe"
  log "Done. Tail logs with:  docker compose -f $TARGET/docker-compose.yml logs -f telegram-bot alert-dispatcher"
}

install_docker
clone_or_update
ensure_env
bring_up
