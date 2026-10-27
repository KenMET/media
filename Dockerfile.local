ARG MEDIA_BASE_IMAGE=python:3.12-slim-bookworm
FROM ${MEDIA_BASE_IMAGE}
ARG INSTALL_OCR=true
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LANG=C.UTF-8 \
    MEDIA_STATE_DIR=/state MEDIA_HEALTH_DIR=/state/health \
    MEDIA_NOTIFICATION_LOG=/state/notifications.jsonl \
    MEDIA_DOWNLOAD_ROOT=/data/downloads MEDIA_LIBRARY_ROOT=/data/media_hub \
    SUBTITLE_SCAN_ROOT=/data/downloads \
    MEDIA_SKILL_FILE=/app/skills/media-acquire/SKILL.md
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip ffmpeg mkvtoolnix tesseract-ocr \
      tesseract-ocr-eng tesseract-ocr-jpn tesseract-ocr-kor \
      tesseract-ocr-chi-sim tesseract-ocr-chi-tra \
      tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-spa tesseract-ocr-rus \
      tesseract-ocr-ita tesseract-ocr-por tesseract-ocr-nld tesseract-ocr-pol && \
    if [ "$INSTALL_OCR" = true ] && ! command -v dotnet >/dev/null 2>&1; then \
      . /etc/os-release; \
      curl -fsSL "https://packages.microsoft.com/config/debian/${VERSION_ID}/packages-microsoft-prod.deb" -o /tmp/microsoft.deb && \
      dpkg -i /tmp/microsoft.deb && apt-get update && apt-get install -y --no-install-recommends dotnet-runtime-8.0; \
    fi && \
    if [ "$INSTALL_OCR" = true ] && [ ! -f /opt/PgsToSrt/PgsToSrt.dll ]; then \
      mkdir -p /opt/PgsToSrt && \
      curl -fsSL https://github.com/Tentacule/PgsToSrt/releases/download/v1.4.8/PgsToStr-1.4.8.zip -o /tmp/pgs.zip && \
      unzip -q /tmp/pgs.zip -d /opt/PgsToSrt; \
      pgs_dll="$(find /opt/PgsToSrt -name PgsToSrt.dll -type f | head -n 1)"; \
      test -n "$pgs_dll" && { [ "$pgs_dll" = /opt/PgsToSrt/PgsToSrt.dll ] || cp -a "$(dirname "$pgs_dll")/." /opt/PgsToSrt/; }; \
    fi && rm -rf /var/lib/apt/lists/* /tmp/microsoft.deb /tmp/pgs.zip
WORKDIR /app
COPY pyproject.toml /app/
RUN python3 -c "import subprocess,tomllib; subprocess.check_call(['pip','install','--no-cache-dir',*tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']])"
COPY src /app/src
COPY skills /app/skills
RUN pip install --no-cache-dir --no-deps .
CMD ["media-mcp"]
