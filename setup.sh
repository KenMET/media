#!/bin/sh
# Each dependency URL selects an existing service; empty selects its bundled container.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
umask 077
topology=standalone
compose_file=compose.local.yml
case "${1:-up}" in
    cloud) topology=cloud; compose_file=compose.cloud.yml; shift ;;
    local) topology=local; shift ;;
esac
command="${1:-up}"
if ! command -v docker >/dev/null 2>&1; then
    echo 'Install and start Docker and Docker Compose.' >&2; exit 1
fi
if docker compose version >/dev/null 2>&1; then
    compose() { docker compose --env-file .env -f "$compose_file" "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
    compose() { docker-compose --env-file .env -f "$compose_file" "$@"; }
else
    echo 'Docker Compose was not found.' >&2; exit 1
fi
if [ ! -f .env ]; then
    cp .env.example .env
    echo 'Created .env; configure dependency addresses and credentials for this deployment.'
fi
chmod 600 .env
setting() { sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r'; }
# New role-specific names win over legacy aliases, without rewriting private .env.
selected() {
    for setting_name in "$@"; do
        setting_value="$(printenv "$setting_name" 2>/dev/null || true)"
        if [ -z "$setting_value" ]; then setting_value="$(setting "$setting_name")"; fi
        if [ -n "$setting_value" ]; then printf '%s' "$setting_value"; return 0; fi
    done
}
MEDIA_LOCAL_STATE_PATH="$(selected MEDIA_LOCAL_STATE_PATH MEDIA_STATE_PATH)"
MEDIA_LOCAL_STATE_PATH="${MEDIA_LOCAL_STATE_PATH:-./state}"
MEDIA_LOCAL_DATA_DIR="$(selected MEDIA_LOCAL_DATA_DIR MEDIA_DATA_DIR)"
MEDIA_LOCAL_DATA_DIR="${MEDIA_LOCAL_DATA_DIR:-./data}"
MEDIA_LOCAL_IMAGE="$(selected MEDIA_LOCAL_IMAGE MEDIA_IMAGE)"
MEDIA_LOCAL_IMAGE="${MEDIA_LOCAL_IMAGE:-media-mcp:local}"
export MEDIA_LOCAL_STATE_PATH MEDIA_LOCAL_DATA_DIR MEDIA_LOCAL_IMAGE
state_path="$MEDIA_LOCAL_STATE_PATH"
data_path="$MEDIA_LOCAL_DATA_DIR"
QBITTORRENT_URL="${QBITTORRENT_URL-$(setting QBITTORRENT_URL)}"
JACKETT_URL="${JACKETT_URL-$(setting JACKETT_URL)}"
MEDIA_CATALOG_URL="${MEDIA_CATALOG_URL-$(setting MEDIA_CATALOG_URL)}"
MEDIA_CONTROL_URL="$(selected MEDIA_CLOUD_CONTROL_URL MEDIA_CONTROL_URL)"
MEDIA_CONTROL_PORT="$(selected MEDIA_CLOUD_CONTROL_PORT MEDIA_CONTROL_PORT)"
MEDIA_EXECUTION_ONLY="${MEDIA_EXECUTION_ONLY-$(setting MEDIA_EXECUTION_ONLY)}"
if [ "$topology" = local ] && [ -z "$MEDIA_CATALOG_URL" ]; then
    MEDIA_EXECUTION_ONLY="${MEDIA_EXECUTION_ONLY:-true}"
fi
MEDIA_EXECUTION_ONLY="${MEDIA_EXECUTION_ONLY:-false}"
if [ "$topology" = cloud ] && [ -z "$MEDIA_CONTROL_URL" ]; then
    MEDIA_CONTROL_PORT="${MEDIA_CONTROL_PORT:-28213}"
fi
if [ -n "$MEDIA_CONTROL_PORT" ]; then
    case "$MEDIA_CONTROL_PORT" in *[!0-9]*) echo 'The control mapping port must be a number from 1 to 65535.' >&2; exit 1 ;; esac
    if [ "$MEDIA_CONTROL_PORT" -lt 1 ] || [ "$MEDIA_CONTROL_PORT" -gt 65535 ]; then
        echo 'The control mapping port must be a number from 1 to 65535.' >&2; exit 1
    fi
fi
MEDIA_CLOUD_CONTROL_PORT="$MEDIA_CONTROL_PORT"
MEDIA_CLOUD_CONTROL_URL="$MEDIA_CONTROL_URL"
export MEDIA_CLOUD_CONTROL_PORT MEDIA_CLOUD_CONTROL_URL MEDIA_CONTROL_PORT MEDIA_EXECUTION_ONLY
MEDIA_WEB_PUBLIC="${MEDIA_WEB_PUBLIC-$(setting MEDIA_WEB_PUBLIC)}"
legacy_public="$MEDIA_WEB_PUBLIC"
MEDIA_WEB_PUBLIC="${MEDIA_WEB_PUBLIC:-false}"
MEDIA_WEB_MODE="${MEDIA_WEB_MODE-$(setting MEDIA_WEB_MODE)}"
if [ -z "$MEDIA_WEB_MODE" ]; then
    if [ "$topology" = cloud ] && [ -z "$legacy_public" ]; then MEDIA_WEB_MODE=proxy; else MEDIA_WEB_MODE=lan; fi
fi
case "$MEDIA_WEB_MODE" in lan|proxy) ;; *) echo 'MEDIA_WEB_MODE must be lan or proxy.' >&2; exit 1 ;; esac
MEDIA_WEB_BIND_HOST="${MEDIA_WEB_BIND_HOST-$(setting MEDIA_WEB_BIND_HOST)}"
MEDIA_SERVICE_PAIRING="${MEDIA_SERVICE_PAIRING-$(setting MEDIA_SERVICE_PAIRING)}"
if [ "$topology" = local ] || [ "$topology" = standalone ]; then
    local_control_bind="${MEDIA_LOCAL_CONTROL_BIND-$(setting MEDIA_LOCAL_CONTROL_BIND)}"
    default_control_bind=0.0.0.0
    if [ "$topology" = local ]; then default_control_bind=127.0.0.1; fi
    MEDIA_WEB_BIND_HOST="${local_control_bind:-${MEDIA_WEB_BIND_HOST:-$default_control_bind}}"
    if [ "$topology" = local ] && [ "$MEDIA_WEB_BIND_HOST" != 0.0.0.0 ] && [ "$MEDIA_WEB_BIND_HOST" != :: ]; then
        MEDIA_SERVICE_PAIRING="${MEDIA_SERVICE_PAIRING:-true}"
    fi
elif [ "$topology" = cloud ]; then
    proxy_ips="${MEDIA_PROXY_IPS-$(setting MEDIA_PROXY_IPS)}"
    proxy_bind=0.0.0.0
    if [ "$MEDIA_WEB_MODE" = proxy ]; then proxy_bind=127.0.0.1; fi
    if [ -n "$proxy_ips" ]; then proxy_bind=0.0.0.0; fi
    MEDIA_GATEWAY_BIND="$(selected MEDIA_CLOUD_WEB_BIND MEDIA_GATEWAY_BIND)"
    MEDIA_GATEWAY_BIND="${MEDIA_GATEWAY_BIND:-0.0.0.0}"
    MEDIA_WEB_BIND_HOST="$MEDIA_GATEWAY_BIND"
    MEDIA_CLOUD_WEB_BIND="$MEDIA_GATEWAY_BIND"
    export MEDIA_GATEWAY_BIND MEDIA_CLOUD_WEB_BIND
    MEDIA_BIND_HOST="$(selected MEDIA_CLOUD_MCP_BIND MEDIA_BIND_HOST)"; MEDIA_BIND_HOST="${MEDIA_BIND_HOST:-$proxy_bind}"
    export MEDIA_BIND_HOST
fi
MEDIA_WEB_BIND_HOST="${MEDIA_WEB_BIND_HOST:-0.0.0.0}"
MEDIA_SERVICE_PAIRING="${MEDIA_SERVICE_PAIRING:-false}"
export QBITTORRENT_URL JACKETT_URL MEDIA_CATALOG_URL MEDIA_CONTROL_URL MEDIA_WEB_PUBLIC MEDIA_WEB_MODE MEDIA_WEB_BIND_HOST MEDIA_SERVICE_PAIRING
if [ "$topology" = cloud ]; then
    MEDIA_CLOUD_WEB_PORT="$(selected MEDIA_CLOUD_WEB_PORT MEDIA_GATEWAY_PORT MEDIA_WEB_PORT)"
    MEDIA_CLOUD_WEB_PORT="${MEDIA_CLOUD_WEB_PORT:-18214}"
    export MEDIA_CLOUD_WEB_PORT
fi
managed_services=''
app_services='local-mcp local-worker local-control'
stop_services='local-worker local-mcp local-control'
build_service=local-mcp
http_service=local-control
health_service=local-mcp
health_port="$(selected MEDIA_LOCAL_MCP_PORT MEDIA_MCP_PORT)"; health_port="${health_port:-18210}"
legacy_services='worker mcp web'
legacy_project=media-standalone
if [ "$topology" = cloud ]; then
    app_services='cloud-mcp cloud-web'; stop_services='cloud-mcp cloud-web'
    build_service=cloud-mcp; http_service=cloud-web; health_service=cloud-mcp
    health_port="$(selected MEDIA_CLOUD_MCP_PORT MEDIA_MCP_PORT)"; health_port="${health_port:-18210}"
    legacy_services='mcp web'; legacy_project=media-cloud
    if [ -z "$JACKETT_URL" ]; then managed_services='jackett'; fi
elif [ "$topology" = local ]; then
    app_services='local-worker local-control'; stop_services='local-worker local-control'; health_service=local-control
    health_port="$(selected MEDIA_LOCAL_CONTROL_PORT MEDIA_WEB_PORT)"
    health_port="${health_port:-18213}"
    if [ -z "$QBITTORRENT_URL" ]; then managed_services='qbittorrent'; fi
    if [ "$MEDIA_EXECUTION_ONLY" != true ] && [ -z "$JACKETT_URL" ] && [ -z "$MEDIA_CATALOG_URL" ]; then managed_services="$managed_services jackett"; fi
else
    if [ -z "$QBITTORRENT_URL" ]; then managed_services='qbittorrent'; fi
    if [ -z "$JACKETT_URL" ] && [ -z "$MEDIA_CATALOG_URL" ]; then managed_services="$managed_services jackett"; fi
fi
case "$command" in
    status) compose ps; exit 0 ;;
    logs) compose logs --tail=80 $app_services $managed_services; exit 0 ;;
    stop) compose stop $stop_services $managed_services; exit 0 ;;
    pair)
        if [ "$topology" != local ] || [ "$MEDIA_SERVICE_PAIRING" != true ]; then
            echo 'Re-pairing requires a local control service explicitly bound to a loopback address.' >&2; exit 1
        fi
        rm -f "$state_path/control-pairing.sealed"
        echo 'Cloud re-pairing is enabled. Confirm FRP is loopback-only, then run setup.sh cloud.'; exit 0 ;;
    up) ;;
    control)
        if [ "$topology" != local ]; then echo 'control only updates the NAS control service.' >&2; exit 2; fi
        app_services='local-control'; managed_services=''; legacy_services=''
        ;;
    *) echo 'Usage: sh setup.sh [cloud|local] [up|status|logs|stop|pair|control]' >&2; exit 2 ;;
esac
case "$health_port" in ''|*[!0-9]*) echo 'The health-check port must be numeric.' >&2; exit 1 ;; esac
if [ "$MEDIA_WEB_PUBLIC" = true ] && [ "$MEDIA_WEB_MODE" != proxy ]; then
    public_url="${MEDIA_WEB_PUBLIC_URL-$(setting MEDIA_WEB_PUBLIC_URL)}"
    case "$public_url" in https://?*) ;; *) echo 'Public access requires MEDIA_WEB_PUBLIC_URL=https://your-exact-domain and TLS on the reverse proxy.' >&2; exit 1 ;; esac
    admin_bind="${MEDIA_ADMIN_BIND-$(setting MEDIA_ADMIN_BIND)}"; admin_bind="${admin_bind:-127.0.0.1}"
    if [ -n "$managed_services" ] && [ "$admin_bind" != 127.0.0.1 ]; then
        echo 'Public deployments require MEDIA_ADMIN_BIND=127.0.0.1 for the built-in admin port.' >&2; exit 1
    fi
fi
multi_user="${MEDIA_MULTI_USER-$(setting MEDIA_MULTI_USER)}"
auth_mode="${MEDIA_AUTH_MODE-$(setting MEDIA_AUTH_MODE)}"; auth_mode="${auth_mode:-none}"
if [ "$multi_user" = true ] && [ "$topology" = standalone ] && [ "$auth_mode" != platform ]; then
    echo 'Multiuser standalone deployments require MEDIA_AUTH_MODE=platform; personal LAN mode remains unauthenticated by default.' >&2; exit 1
fi
control_file="$(setting MEDIA_CONTROL_TOKEN_FILE)"; control_file="${control_file:-./state/control-token}"
create_control=false
pair_control=false
if [ "$topology" = cloud ]; then
    if [ "$MEDIA_WEB_PUBLIC" = true ] && [ "$MEDIA_WEB_MODE" != proxy ] && [ -z "$(setting MEDIA_ALLOWED_HOSTS)" ]; then
        echo 'Public cloud deployments require exact MEDIA_ALLOWED_HOSTS.' >&2; exit 1
    fi
    if [ ! -s "$control_file" ]; then
        if [ "$MEDIA_WEB_MODE" = proxy ]; then
            mkdir -p "$(dirname -- "$control_file")"
            pair_control=true
        elif [ "$MEDIA_WEB_PUBLIC" = true ] || [ "$control_file" != ./state/control-token ]; then
            echo 'Configure an existing MEDIA_CONTROL_TOKEN_FILE. Transfer the token file securely between hosts, never through chat.' >&2; exit 1
        else
            mkdir -p ./state
            create_control=true
        fi
    fi
    cloud_state="$(setting MEDIA_CLOUD_STATE_PATH)"; mkdir -p "${cloud_state:-./state-cloud}"
else
    mkdir -p "$state_path" "$data_path/downloads" "$data_path/media_hub"
    if [ ! -s "$control_file" ]; then
        if [ "$control_file" != ./state/control-token ]; then
            echo 'MEDIA_CONTROL_TOKEN_FILE points to a missing file.' >&2; exit 1
        fi
        mkdir -p ./state
        create_control=true
    fi
    token_file="$(setting CODEX_TOKEN_FILE)"; token_file="${token_file:-./state/codex-token}"
    if [ ! -f "$token_file" ]; then
        if [ "$token_file" != ./state/codex-token ]; then
            echo 'CODEX_TOKEN_FILE points to a missing file. Correct .env.' >&2; exit 1
        fi
        mkdir -p ./state; : > "$token_file"; chmod 600 "$token_file"
        echo 'Model credentials are not configured. Web/MCP may start; intelligent processing waits for the model connection.'
    fi
fi
compose build "$build_service"
if [ "$pair_control" = true ]; then
    pairing_parent="$(CDPATH= cd -- "$(dirname -- "$control_file")" && pwd)"
    pairing_name="$(basename -- "$control_file")"
    pairing_image="${MEDIA_CLOUD_IMAGE-$(setting MEDIA_CLOUD_IMAGE)}"; pairing_image="${pairing_image:-media-mcp-cloud:local}"
    docker run --rm --network host --entrypoint python3 -e MEDIA_CLOUD_CONTROL_URL -e MEDIA_CLOUD_CONTROL_PORT -e MEDIA_CONTROL_URL -e MEDIA_CONTROL_PORT \
        -v "$pairing_parent:/pairing" "$pairing_image" \
        -m media_mcp.platform.pairing "/pairing/$pairing_name"
    if [ ! -s "$control_file" ]; then echo 'Automatic pairing did not produce internal credentials. Startup stopped.' >&2; exit 1; fi
fi
if [ "$create_control" = true ]; then
    # OpenWrt may not ship od/openssl; Python is already guaranteed by our image.
    if [ "$topology" = cloud ]; then
        token_image="${MEDIA_CLOUD_IMAGE-$(setting MEDIA_CLOUD_IMAGE)}"
        token_image="${token_image:-media-mcp-cloud:local}"
    else
        token_image="$MEDIA_LOCAL_IMAGE"
        token_image="${token_image:-media-mcp:local}"
    fi
    token_temp="$control_file.tmp.$$"
    if ! docker run --rm --network none --entrypoint python3 "$token_image" -c 'import secrets;print(secrets.token_urlsafe(40))' > "$token_temp"; then
        rm -f "$token_temp"
        echo 'Cannot generate the control channel token.' >&2; exit 1
    fi
    if [ ! -s "$token_temp" ]; then
        rm -f "$token_temp"
        echo 'The generated control channel token is empty.' >&2; exit 1
    fi
    chmod 600 "$token_temp"
    mv "$token_temp" "$control_file"
fi
for service in $managed_services; do
    compose run --rm --no-deps "init-$service"
    compose up -d "$service"
    case "$service" in
        qbittorrent) probe=http://127.0.0.1:8080/api/v2/app/version ;;
        jackett) probe=http://127.0.0.1:9117/UI/Dashboard ;;
    esac
    attempt=0
    while ! compose exec -T "$service" curl --max-time 3 -fsS "$probe" >/dev/null 2>&1; do
        attempt=$((attempt+1))
        if [ "$attempt" -ge 60 ]; then
            printf '%s is not ready; inspect setup.sh logs for that deployment.\n' "$service" >&2; exit 1
        fi
        sleep 5
    done
done
# Keep the Compose project identifier and dependency containers stable. Only the
# old application service keys are retired; no volume or state directory is removed.
for legacy_service in $legacy_services; do
    legacy_ids="$(docker ps --all --filter "label=com.docker.compose.project=$legacy_project" \
        --filter "label=com.docker.compose.service=$legacy_service" --format '{{.ID}}')"
    for legacy_id in $legacy_ids; do
        legacy_dir="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$legacy_id")"
        legacy_dir="$(CDPATH= cd -- "$legacy_dir" 2>/dev/null && pwd -P || true)"
        if [ "$legacy_dir" != "$(pwd -P)" ]; then continue; fi
        printf 'Migrate legacy application service %s; preserve state directories and media mounts.\n' "$legacy_service"
        docker stop "$legacy_id" >/dev/null
        docker rm "$legacy_id" >/dev/null
    done
done
compose up -d $app_services
wait_for_entry() {
    entry_service="$1"; entry_port="$2"; entry_label="$3"
    entry_host="${4:-127.0.0.1}"
    case "$entry_host" in 0.0.0.0|::) entry_host=127.0.0.1 ;; esac
    case "$entry_host" in *:*) entry_host="[$entry_host]" ;; esac
    entry_url="http://$entry_host:$entry_port/healthz"
    entry_logs_command='sh setup.sh logs'
    if [ "$topology" != standalone ]; then entry_logs_command="sh setup.sh $topology logs"; fi
    printf 'Waiting for %s (local port %s)...\n' "$entry_label" "$entry_port"
    entry_attempt=0
    while [ "$entry_attempt" -lt 60 ]; do
        if compose exec -T "$entry_service" python3 -c 'import sys,urllib.request;urllib.request.urlopen(sys.argv[1],timeout=2)' "$entry_url" >/dev/null 2>&1; then
            printf '%s is ready.\n' "$entry_label"
            return 0
        fi
        entry_container="$(compose ps --all --quiet "$entry_service" 2>/dev/null | head -n 1)"
        if [ -n "$entry_container" ]; then
            entry_state="$(docker inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "$entry_container" 2>/dev/null || true)"
            case "$entry_state" in
                restarting:*|exited:*|dead:*)
                    printf '%s is not ready; container state: %s. Check whether port %s is occupied and inspect %s.\n' "$entry_label" "$entry_state" "$entry_port" "$entry_logs_command" >&2
                    printf 'Continue checking every 5 seconds for service recovery.\n' >&2 ;;
            esac
        fi
        entry_attempt=$((entry_attempt+1))
        if [ $((entry_attempt % 5)) -eq 0 ]; then
            printf '%s is still not ready after %s checks; port %s.\n' "$entry_label" "$entry_attempt" "$entry_port"
        fi
        sleep 5
    done
    printf 'Timed out waiting for %s; inspect setup.sh logs for that deployment.\n' "$entry_label" >&2
    return 1
}
entry_label='Local MCP'
if [ "$topology" = cloud ]; then entry_label='Cloud MCP'; fi
entry_bind=127.0.0.1
if [ "$topology" = local ]; then entry_label='Local control API'; fi
if [ "$topology" = local ]; then entry_bind="$MEDIA_WEB_BIND_HOST"; fi
if ! wait_for_entry "$health_service" "$health_port" "$entry_label" "$entry_bind"; then exit 1; fi
web_port="$(selected MEDIA_LOCAL_CONTROL_PORT MEDIA_WEB_PORT)"
if [ "$topology" = cloud ]; then
    web_port="$(selected MEDIA_CLOUD_WEB_PORT MEDIA_GATEWAY_PORT MEDIA_WEB_PORT)"; web_port="${web_port:-18214}"
else
    local_control_port="${MEDIA_LOCAL_CONTROL_PORT-$(setting MEDIA_LOCAL_CONTROL_PORT)}"
    web_port="${local_control_port:-${web_port:-18213}}"
fi
case "$web_port" in ''|*[!0-9]*) echo 'The web port must be numeric.' >&2; exit 1 ;; esac
if [ "$health_service" != "$http_service" ]; then
    if ! wait_for_entry "$http_service" "$web_port" 'Cloud web gateway' "$MEDIA_WEB_BIND_HOST"; then exit 1; fi
fi
lan_ip="$(setting MEDIA_LAN_IP)"
if [ -z "$lan_ip" ] && command -v ip >/dev/null 2>&1; then
    lan_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([^ ]*\).*/\1/p' | head -n 1)"
fi
lan_ip="${lan_ip:-<host-LAN-IP>}"
if [ "$topology" = local ] && [ "$MEDIA_WEB_BIND_HOST" != 0.0.0.0 ] && [ "$MEDIA_WEB_BIND_HOST" != :: ]; then
    lan_ip="$MEDIA_WEB_BIND_HOST"
fi
if [ "$topology" = cloud ]; then
    printf 'Cloud started: web port %s, MCP port %s. Use your existing reverse proxy for the domain and HTTPS.\n' "$web_port" "$health_port"
elif [ "$topology" = local ]; then
    printf 'Local control service started: http://%s:%s\n' "$lan_ip" "$web_port"
else
    printf '\nMCP started: http://%s:%s/mcp (authentication mode: %s)\n' "$lan_ip" "$health_port" "$auth_mode"
    printf 'Media website: http://%s:%s\n' "$lan_ip" "$web_port"
fi
if [ "$topology" = cloud ]; then
    echo 'Initial web administrator: the bootstrap token is in web-bootstrap-token under the NAS local state directory, not cloud state-cloud.'
    echo 'On the NAS, run in the project directory: docker compose -f compose.local.yml exec -T local-control cat /state/web-bootstrap-token. View it privately; do not share the token.'
else
    printf 'Initial web administrator: the bootstrap token is at %s/web-bootstrap-token on this host. Do not share the token.\n' "$state_path"
fi
echo 'Dependencies: configured URLs reuse existing services; otherwise the owning deployment starts the bundled container.'
if [ "$topology" = standalone ] && [ "$auth_mode" = none ]; then
    echo 'This is trusted personal LAN MCP. Web user permissions do not restrict this unauthenticated endpoint; limit network reachability.'
fi
if [ "$topology" != cloud ]; then
    echo 'Checking downloader API (read version only; no download submission)...'
    if ! compose exec -T local-worker python3 -m media_mcp.monitor.dependencies; then exit 1; fi
    echo 'Waiting for worker initialization (model connection and directory checks)...'
    worker_ready=false; worker_attempt=0
    while [ "$worker_attempt" -lt 60 ]; do
        if compose exec -T local-worker python3 -m media_mcp.monitor.health >/dev/null 2>&1; then
            worker_ready=true; break
        fi
        worker_attempt=$((worker_attempt+1))
        if [ $((worker_attempt % 5)) -eq 0 ]; then
            printf 'The worker is still initializing or retrying after %s checks.\n' "$worker_attempt"
        fi
        sleep 5
    done
    if [ "$worker_ready" = true ]; then echo 'Background worker: ready.'
    else echo 'Worker readiness timed out. Deployment is not ready; inspect setup.sh logs for model and directory errors.' >&2; exit 1; fi
    echo 'Local control API, downloader and worker checks all passed.'
fi
