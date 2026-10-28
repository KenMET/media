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
    echo '需要安装并启动 Docker，以及 Docker Compose。' >&2; exit 1
fi
if docker compose version >/dev/null 2>&1; then
    compose() { docker compose --env-file .env -f "$compose_file" "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
    compose() { docker-compose --env-file .env -f "$compose_file" "$@"; }
else
    echo '没有找到 Docker Compose。' >&2; exit 1
fi
if [ ! -f .env ]; then
    cp .env.example .env
    echo '已创建 .env；请按部署位置填写已有依赖地址和凭据。'
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
    case "$MEDIA_CONTROL_PORT" in *[!0-9]*) echo '控制映射端口必须是 1–65535 的数字。' >&2; exit 1 ;; esac
    if [ "$MEDIA_CONTROL_PORT" -lt 1 ] || [ "$MEDIA_CONTROL_PORT" -gt 65535 ]; then
        echo '控制映射端口必须是 1–65535 的数字。' >&2; exit 1
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
case "$MEDIA_WEB_MODE" in lan|proxy) ;; *) echo 'MEDIA_WEB_MODE 只支持 lan 或 proxy。' >&2; exit 1 ;; esac
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
            echo '重新连接只用于显式本机地址监听的 local 控制端。' >&2; exit 1
        fi
        rm -f "$state_path/control-pairing.sealed"
        echo '已允许云端重新连接；确认 FRP 仅本机可达后，运行 setup.sh cloud。'; exit 0 ;;
    up) ;;
    *) echo '用法：sh setup.sh [cloud|local] [up|status|logs|stop|pair]' >&2; exit 2 ;;
esac
case "$health_port" in ''|*[!0-9]*) echo '健康检查端口必须是数字。' >&2; exit 1 ;; esac
if [ "$MEDIA_WEB_PUBLIC" = true ] && [ "$MEDIA_WEB_MODE" != proxy ]; then
    public_url="${MEDIA_WEB_PUBLIC_URL-$(setting MEDIA_WEB_PUBLIC_URL)}"
    case "$public_url" in https://?*) ;; *) echo '公网入口需配置 MEDIA_WEB_PUBLIC_URL=https://准确域名，并在反向代理配置 TLS。' >&2; exit 1 ;; esac
    admin_bind="${MEDIA_ADMIN_BIND-$(setting MEDIA_ADMIN_BIND)}"; admin_bind="${admin_bind:-127.0.0.1}"
    if [ -n "$managed_services" ] && [ "$admin_bind" != 127.0.0.1 ]; then
        echo '公网部署的内置管理端口必须使用 MEDIA_ADMIN_BIND=127.0.0.1。' >&2; exit 1
    fi
fi
multi_user="${MEDIA_MULTI_USER-$(setting MEDIA_MULTI_USER)}"
auth_mode="${MEDIA_AUTH_MODE-$(setting MEDIA_AUTH_MODE)}"; auth_mode="${auth_mode:-none}"
if [ "$multi_user" = true ] && [ "$topology" = standalone ] && [ "$auth_mode" != platform ]; then
    echo '多人独立部署需显式设置 MEDIA_AUTH_MODE=platform；个人 LAN 默认模式保持免认证。' >&2; exit 1
fi
control_file="$(setting MEDIA_CONTROL_TOKEN_FILE)"; control_file="${control_file:-./state/control-token}"
create_control=false
pair_control=false
if [ "$topology" = cloud ]; then
    if [ "$MEDIA_WEB_PUBLIC" = true ] && [ "$MEDIA_WEB_MODE" != proxy ] && [ -z "$(setting MEDIA_ALLOWED_HOSTS)" ]; then
        echo '公网 cloud 部署需设置准确的 MEDIA_ALLOWED_HOSTS。' >&2; exit 1
    fi
    if [ ! -s "$control_file" ]; then
        if [ "$MEDIA_WEB_MODE" = proxy ]; then
            mkdir -p "$(dirname -- "$control_file")"
            pair_control=true
        elif [ "$MEDIA_WEB_PUBLIC" = true ] || [ "$control_file" != ./state/control-token ]; then
            echo '请配置已有的 MEDIA_CONTROL_TOKEN_FILE；拆机时安全同步令牌文件，不要在聊天中传递内容。' >&2; exit 1
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
            echo 'MEDIA_CONTROL_TOKEN_FILE 指向的文件不存在。' >&2; exit 1
        fi
        mkdir -p ./state
        create_control=true
    fi
    token_file="$(setting CODEX_TOKEN_FILE)"; token_file="${token_file:-./state/codex-token}"
    if [ ! -f "$token_file" ]; then
        if [ "$token_file" != ./state/codex-token ]; then
            echo 'CODEX_TOKEN_FILE 指向的文件不存在，请修正 .env。' >&2; exit 1
        fi
        mkdir -p ./state; : > "$token_file"; chmod 600 "$token_file"
        echo '尚未配置模型凭据：网页/MCP 可以启动，智能处理等待模型连接。'
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
    if [ ! -s "$control_file" ]; then echo '自动连接没有生成内部凭据，停止启动。' >&2; exit 1; fi
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
        echo '无法生成控制通道令牌。' >&2; exit 1
    fi
    if [ ! -s "$token_temp" ]; then
        rm -f "$token_temp"
        echo '控制通道令牌生成为空。' >&2; exit 1
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
            printf '%s 尚未就绪，请查看相应部署的 setup.sh logs。\n' "$service" >&2; exit 1
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
        printf '迁移旧应用服务 %s；保留状态目录和媒体挂载。\n' "$legacy_service"
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
    printf '正在等待%s就绪（本机端口 %s）...\n' "$entry_label" "$entry_port"
    entry_attempt=0
    while [ "$entry_attempt" -lt 60 ]; do
        if compose exec -T "$entry_service" python3 -c 'import sys,urllib.request;urllib.request.urlopen(sys.argv[1],timeout=2)' "$entry_url" >/dev/null 2>&1; then
            printf '%s已就绪。\n' "$entry_label"
            return 0
        fi
        entry_container="$(compose ps --all --quiet "$entry_service" 2>/dev/null | head -n 1)"
        if [ -n "$entry_container" ]; then
            entry_state="$(docker inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "$entry_container" 2>/dev/null || true)"
            case "$entry_state" in
                restarting:*|exited:*|dead:*)
                    printf '%s尚未就绪，容器状态 %s。请检查端口 %s 是否已被占用，并查看 %s。\n' "$entry_label" "$entry_state" "$entry_port" "$entry_logs_command" >&2
                    printf '继续每 5 秒检查，等待服务恢复。\n' >&2 ;;
            esac
        fi
        entry_attempt=$((entry_attempt+1))
        if [ $((entry_attempt % 5)) -eq 0 ]; then
            printf '%s仍未就绪，已检查 %s 次；端口 %s。\n' "$entry_label" "$entry_attempt" "$entry_port"
        fi
        sleep 5
    done
    printf '%s等待超时，请查看相应部署的 setup.sh logs。\n' "$entry_label" >&2
    return 1
}
entry_label='本地 MCP'
if [ "$topology" = cloud ]; then entry_label='云端 MCP'; fi
entry_bind=127.0.0.1
if [ "$topology" = local ]; then entry_label='本地控制 API'; fi
if [ "$topology" = local ]; then entry_bind="$MEDIA_WEB_BIND_HOST"; fi
if ! wait_for_entry "$health_service" "$health_port" "$entry_label" "$entry_bind"; then exit 1; fi
web_port="$(selected MEDIA_LOCAL_CONTROL_PORT MEDIA_WEB_PORT)"
if [ "$topology" = cloud ]; then
    web_port="$(selected MEDIA_CLOUD_WEB_PORT MEDIA_GATEWAY_PORT MEDIA_WEB_PORT)"; web_port="${web_port:-18214}"
else
    local_control_port="${MEDIA_LOCAL_CONTROL_PORT-$(setting MEDIA_LOCAL_CONTROL_PORT)}"
    web_port="${local_control_port:-${web_port:-18213}}"
fi
case "$web_port" in ''|*[!0-9]*) echo '网页端口必须是数字。' >&2; exit 1 ;; esac
if [ "$health_service" != "$http_service" ]; then
    if ! wait_for_entry "$http_service" "$web_port" '云端网站网关' "$MEDIA_WEB_BIND_HOST"; then exit 1; fi
fi
lan_ip="$(setting MEDIA_LAN_IP)"
if [ -z "$lan_ip" ] && command -v ip >/dev/null 2>&1; then
    lan_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([^ ]*\).*/\1/p' | head -n 1)"
fi
lan_ip="${lan_ip:-<主机局域网IP>}"
if [ "$topology" = local ] && [ "$MEDIA_WEB_BIND_HOST" != 0.0.0.0 ] && [ "$MEDIA_WEB_BIND_HOST" != :: ]; then
    lan_ip="$MEDIA_WEB_BIND_HOST"
fi
if [ "$topology" = cloud ]; then
    printf 'cloud 已启动：网站端口 %s，MCP 端口 %s；域名和 HTTPS 使用你已有的反向代理。\n' "$web_port" "$health_port"
elif [ "$topology" = local ]; then
    printf '本地控制服务已启动：http://%s:%s\n' "$lan_ip" "$web_port"
else
    printf '\nMCP 已启动：http://%s:%s/mcp（认证模式：%s）\n' "$lan_ip" "$health_port" "$auth_mode"
    printf 'Media 网页：http://%s:%s\n' "$lan_ip" "$web_port"
fi
if [ "$topology" = cloud ]; then
    echo '首次创建网站管理员：初始化令牌在 NAS 的 local 状态目录 web-bootstrap-token，不在云端 state-cloud。'
    echo '请在 NAS 的项目目录执行：docker compose -f compose.local.yml exec -T local-control cat /state/web-bootstrap-token；只在自己的终端查看，不要分享令牌。'
else
    printf '首次创建网站管理员：初始化令牌位于本机 %s/web-bootstrap-token；不要分享令牌。\n' "$state_path"
fi
echo '依赖服务：已配置 URL 的复用已有服务，未配置的仅在所属部署端启动对应容器。'
if [ "$topology" = standalone ] && [ "$auth_mode" = none ]; then
    echo '当前为可信个人 LAN MCP；网页用户权限不约束此免认证入口，请限制端口可达范围。'
fi
if [ "$topology" != cloud ]; then
    echo '正在检查下载器 API（只读取版本，不提交下载）...'
    if ! compose exec -T local-worker python3 -m media_mcp.monitor.dependencies; then exit 1; fi
    echo '正在等待后台 worker 初始化（模型连接与目录检查）...'
    worker_ready=false; worker_attempt=0
    while [ "$worker_attempt" -lt 60 ]; do
        if compose exec -T local-worker python3 -m media_mcp.monitor.health >/dev/null 2>&1; then
            worker_ready=true; break
        fi
        worker_attempt=$((worker_attempt+1))
        if [ $((worker_attempt % 5)) -eq 0 ]; then
            printf '后台 worker 仍在初始化或重试，已检查 %s 次。\n' "$worker_attempt"
        fi
        sleep 5
    done
    if [ "$worker_ready" = true ]; then echo '后台 worker：已就绪。'
    else echo '后台 worker 等待超时：部署尚未就绪，请查看 setup.sh logs 中的模型和目录错误。' >&2; exit 1; fi
    echo '本地控制 API、下载器和后台 worker 检查全部通过。'
fi
