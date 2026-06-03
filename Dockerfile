FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apk add --no-cache tini su-exec ca-certificates

COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev

COPY app/ /app/

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/sbin/tini","--"]
CMD ["/app/entrypoint.sh"]
