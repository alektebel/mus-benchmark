# Public mus table -- serves src/musbench/live/server.py in --public mode.
# Build context is the repo root; see docs/DEPLOY-live.md.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir -e .

COPY assets/cards /app/assets/cards

# musbench.live.server reads MUS_ALLOW_ORIGINS, MUS_SEATS and every MUS_* limit from
# the environment, so the command line stays fixed and Fly tunes via secrets.
ENV MUS_BUDGET_STATE=/tmp/mus-budget.json \
    MUS_SEATS="human,glm5.3-flash,deepseek-v4-flash,qwen3.8-flash" \
    PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "exec python -m musbench.live.server --host 0.0.0.0 --port ${PORT} --seats \"${MUS_SEATS}\" --public"]
