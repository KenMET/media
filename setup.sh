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
state_path="$(setting MEDIA_STATE_PATH)"; state_path="${state_path:-./state}"
data_path="$(setting MEDIA_DATA_DIR)"; data_path="${data_path:-./data}"
QBITTORRENT_URL="${QBITTORRENT_URL-$(setting QBITTORRENT_URL)}"
JACKETT_URL="${JACKETT_URL-$(setting JACKETT_URL)}"
MEDIA_CATALOG_URL="${MEDIA_CATALOG_URL-$(setting MEDIA_CATALOG_URL)}"
MEDIA_CONTROL_URL="${MEDIA_CONTROL_URL-$(setting MEDIA_CONTROL_URL)}"
MEDIA_CONTROL_PORT="${MEDIA_CONTROL_PORT-$(setting MEDIA_CONTROL_PORT)}"
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
export MEDIA_CONTROL_PORT MEDIA_EXECUTION_ONLY
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
if [ "$topology" = local ]; then
    MEDIA_WEB_BIND_HOST="${MEDIA_WEB_BIND_HOST:-127.0.0.1}"
    if [ "$MEDIA_WEB_BIND_HOST" = 127.0.0.1 ]; then MEDIA_SERVICE_PAIRING="${MEDIA_SERVICE_PAIRING:-true}"; fi
elif [ "$topology" = cloud ] && [ "$MEDIA_WEB_MODE" = proxy ]; then
    proxy_ips="${MEDIA_PROXY_IPS-$(setting MEDIA_PROXY_IPS)}"
    proxy_bind=127.0.0.1
    if [ -n "$proxy_ips" ]; then proxy_bind=0.0.0.0; fi
    MEDIA_WEB_BIND_HOST="${MEDIA_WEB_BIND_HOST:-$proxy_bind}"
    MEDIA_BIND_HOST="${MEDIA_BIND_HOST-$(setting MEDIA_BIND_HOST)}"; MEDIA_BIND_HOST="${MEDIA_BIND_HOST:-$proxy_bind}"
    export MEDIA_BIND_HOST
fi
MEDIA_WEB_BIND_HOST="${MEDIA_WEB_BIND_HOST:-0.0.0.0}"
MEDIA_SERVICE_PAIRING="${MEDIA_SERVICE_PAIRING:-false}"
export QBITTORRENT_URL JACKETT_URL MEDIA_CATALOG_URL MEDIA_CONTROL_URL MEDIA_WEB_PUBLIC MEDIA_WEB_MODE MEDIA_WEB_BIND_HOST MEDIA_SERVICE_PAIRING
managed_services=''
app_services='mcp worker web'
stop_services='worker mcp web'
health_service=mcp
health_port="$(setting MEDIA_MCP_PORT)"; health_port="${health_port:-18210}"
if [ "$topology" = cloud ]; then
    app_services='mcp web'; stop_services='mcp web'
    if [ -z "$JACKETT_URL" ]; then managed_services='jackett'; fi
elif [ "$topology" = local ]; then
    app_services='worker web'; stop_services='worker web'; health_service=web
    legacy_web_port="$(setting MEDIA_WEB_PORT)"
    health_port="${MEDIA_LOCAL_CONTROL_PORT-$(setting MEDIA_LOCAL_CONTROL_PORT)}"
    health_port="${health_port:-${legacy_web_port:-18213}}"
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
            echo '重新连接只用于本机监听的 local 控制端。' >&2; exit 1
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
compose build mcp
if [ "$pair_control" = true ]; then
    pairing_parent="$(CDPATH= cd -- "$(dirname -- "$control_file")" && pwd)"
    pairing_name="$(basename -- "$control_file")"
    pairing_image="${MEDIA_CLOUD_IMAGE-$(setting MEDIA_CLOUD_IMAGE)}"; pairing_image="${pairing_image:-media-mcp-cloud:local}"
    docker run --rm --network host --entrypoint python3 -e MEDIA_CONTROL_URL -e MEDIA_CONTROL_PORT \
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
        token_image="${MEDIA_IMAGE-$(setting MEDIA_IMAGE)}"
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
        sleep 2
    done
done
compose up -d $app_services
wait_for_entry() {
    entry_service="$1"; entry_port="$2"; entry_label="$3"
    entry_logs_command='sh setup.sh logs'
    if [ "$topology" != standalone ]; then entry_logs_command="sh setup.sh $topology logs"; fi
    printf '正在等待%s就绪（本机端口 %s）...\n' "$entry_label" "$entry_port"
    entry_attempt=0
    while [ "$entry_attempt" -lt 60 ]; do
        if compose exec -T "$entry_service" python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$entry_port/healthz',timeout=2)" >/dev/null 2>&1; then
            printf '%s已就绪。\n' "$entry_label"
            return 0
        fi
        entry_container="$(compose ps --all --quiet "$entry_service" 2>/dev/null | head -n 1)"
        if [ -n "$entry_container" ]; then
            entry_state="$(docker inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "$entry_container" 2>/dev/null || true)"
            case "$entry_state" in
                restarting:*|exited:*|dead:*)
                    printf '%s启动失败，容器状态 %s。请检查端口 %s 是否已被占用，并查看 %s。\n' "$entry_label" "$entry_state" "$entry_port" "$entry_logs_command" >&2
                    return 1 ;;
            esac
        fi
        entry_attempt=$((entry_attempt+1))
        if [ $((entry_attempt % 5)) -eq 0 ]; then
            printf '%s仍未就绪，已检查 %s 次；端口 %s。\n' "$entry_label" "$entry_attempt" "$entry_port"
        fi
        sleep 2
    done
    printf '%s等待超时，请查看相应部署的 setup.sh logs。\n' "$entry_label" >&2
    return 1
}
entry_label='MCP'
if [ "$topology" = local ]; then entry_label='本地控制 API'; fi
if ! wait_for_entry "$health_service" "$health_port" "$entry_label"; then exit 1; fi
web_port="$(setting MEDIA_WEB_PORT)"
if [ "$topology" = cloud ]; then
    gateway_port="$(setting MEDIA_GATEWAY_PORT)"; web_port="${gateway_port:-${web_port:-18214}}"
else
    local_control_port="${MEDIA_LOCAL_CONTROL_PORT-$(setting MEDIA_LOCAL_CONTROL_PORT)}"
    web_port="${local_control_port:-${web_port:-18213}}"
fi
case "$web_port" in ''|*[!0-9]*) echo '网页端口必须是数字。' >&2; exit 1 ;; esac
if [ "$health_service" != web ]; then
    if ! wait_for_entry web "$web_port" '网页入口'; then exit 1; fi
fi
lan_ip="$(setting MEDIA_LAN_IP)"
if [ -z "$lan_ip" ] && command -v ip >/dev/null 2>&1; then
    lan_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([^ ]*\).*/\1/p' | head -n 1)"
fi
lan_ip="${lan_ip:-<主机局域网IP>}"
if [ "$topology" = cloud ]; then
    printf 'cloud 已启动：网站端口 %s，MCP 端口 %s；域名和 HTTPS 使用你已有的反向代理。\n' "$web_port" "$health_port"
elif [ "$topology" = local ]; then
    printf '本地控制服务已启动：http://%s:%s\n' "$lan_ip" "$web_port"
else
    printf '\nMCP 已启动：http://%s:%s/mcp（认证模式：%s）\n' "$lan_ip" "$health_port" "$auth_mode"
    printf 'Media 网页：http://%s:%s\n' "$lan_ip" "$web_port"
fi
echo '首次使用网页：在本地状态目录 web-bootstrap-token 文件取得初始化令牌，创建管理员；不要分享令牌。'
echo '依赖服务：已配置 URL 的复用已有服务，未配置的仅在所属部署端启动对应容器。'
if [ "$topology" = standalone ] && [ "$auth_mode" = none ]; then
    echo '当前为可信个人 LAN MCP；网页用户权限不约束此免认证入口，请限制端口可达范围。'
fi
if [ "$topology" != cloud ]; then
    if compose exec -T worker python3 -m media_mcp.monitor.health >/dev/null 2>&1; then
        echo '后台 worker：已就绪。'
    else
        echo '后台 worker：尚未就绪，请检查模型连接、目录权限与日志。'
    fi
fi
