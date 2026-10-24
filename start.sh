#!/bin/sh
# Personal LAN bundle: Media + SQLite + qBittorrent + Jackett.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
umask 077
if ! command -v docker >/dev/null 2>&1; then
    echo '需要安装并启动 Docker，以及 Docker Compose。' >&2; exit 1
fi
if docker compose version >/dev/null 2>&1; then
    compose() { docker compose --env-file .env -f compose.yml "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
    compose() { docker-compose --env-file .env -f compose.yml "$@"; }
else
    echo '没有找到 Docker Compose。' >&2; exit 1
fi
if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo '已创建 .env；本地数据库和 MCP 不需要账号或认证密钥。'
fi
# Existing env files may have been created by an editor with permissive modes.
chmod 600 .env
setting() { sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '\r'; }
state_path="$(setting MEDIA_STATE_PATH)"; state_path="${state_path:-./state}"
data_path="$(setting MEDIA_DATA_DIR)"; data_path="${data_path:-./data}"
services_path="$(setting MEDIA_SERVICES_DIR)"; services_path="${services_path:-./services}"
command="${1:-up}"
case "$command" in
    status) compose ps; exit 0 ;;
    logs) compose logs --tail=80 mcp worker qbittorrent jackett; exit 0 ;;
    stop) compose stop worker mcp qbittorrent jackett; exit 0 ;;
    up) ;;
    *) echo '用法：./start.sh [up|status|logs|stop]' >&2; exit 2 ;;
esac
mkdir -p "$state_path" "$data_path/downloads" "$data_path/media_hub" "$services_path/qbittorrent" "$services_path/jackett"
token_file="$(setting CODEX_TOKEN_FILE)"; token_file="${token_file:-./state/codex-token}"
if [ ! -f "$token_file" ]; then
    if [ "$token_file" != ./state/codex-token ]; then
        echo 'CODEX_TOKEN_FILE 指向的文件不存在，请修正 .env。' >&2; exit 1
    fi
    mkdir -p ./state
    : > "$token_file"
    chmod 600 "$token_file"
    echo '尚未配置模型凭据：MCP、下载器与 Jackett 可以启动，智能处理等待模型连接。'
fi
compose build mcp
compose run --rm --no-deps init
compose up -d qbittorrent jackett mcp worker
port="$(setting MEDIA_MCP_PORT)"; port="${port:-18210}"
case "$port" in ''|*[!0-9]*) echo 'MEDIA_MCP_PORT 必须是数字。' >&2; exit 1 ;; esac
ready=false; attempt=0
while [ "$attempt" -lt 60 ]; do
    if compose exec -T mcp python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$port/healthz',timeout=2)" >/dev/null 2>&1; then
        ready=true; break
    fi
    attempt=$((attempt+1)); sleep 2
done
if [ "$ready" != true ]; then echo 'MCP 尚未就绪，请运行 ./start.sh logs。' >&2; exit 1; fi
lan_ip="$(setting MEDIA_LAN_IP)"
if [ -z "$lan_ip" ] && command -v ip >/dev/null 2>&1; then
    lan_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([^ ]*\).*/\1/p' | head -n 1)"
fi
lan_ip="${lan_ip:-<主机局域网IP>}"
qport="$(setting MEDIA_QBITTORRENT_PORT)"; qport="${qport:-18211}"
jport="$(setting MEDIA_JACKETT_PORT)"; jport="${jport:-18212}"
auth_mode="$(setting MEDIA_AUTH_MODE)"; auth_mode="${auth_mode:-none}"
printf '\nMCP 已启动：http://%s:%s/mcp（认证模式：%s）\n' "$lan_ip" "$port" "$auth_mode"
printf '本机健康检查：http://127.0.0.1:%s/healthz\n' "$port"
printf 'qBittorrent：http://%s:%s\nJackett：http://%s:%s\n' "$lan_ip" "$qport" "$lan_ip" "$jport"
echo '数据库：state/media.sqlite3。请在 Jackett 页面添加你使用的资源站；内部 API key 自动管理。'
if compose exec -T worker python3 -m media_mcp.monitor.health >/dev/null 2>&1; then
    echo '后台 worker：已就绪。'
else
    echo '后台 worker：尚未就绪，请检查模型连接与 ./start.sh logs。'
fi
