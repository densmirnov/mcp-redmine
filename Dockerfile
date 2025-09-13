FROM python:3.13-slim

WORKDIR /app

COPY . /app

RUN pip install --upgrade pip \
    && pip install uv \
    && uv sync

ENV PORT=8369
EXPOSE 8369

CMD ["uv", "run", "--directory", "/app", "-m", "mcp_redmine.server", "main"]
