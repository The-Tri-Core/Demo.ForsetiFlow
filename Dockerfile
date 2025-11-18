FROM docker.io/library/python:3.14.0-bookworm AS compiler

WORKDIR /app

RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

FROM docker.io/library/python:3.14.0-slim AS runner

WORKDIR /app
COPY --from=compiler /app/.venv /app/.venv

COPY . /app/

ENV PATH="/app/.venv/bin:$PATH"
ENV PROJECT_DATA_DIR=/app/instance
ENV PORT=5000

EXPOSE $PORT

CMD ["sh", "-c", "python -m flask run --host=0.0.0.0 --port=${PORT}"]
