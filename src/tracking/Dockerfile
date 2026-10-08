FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MLFLOW_DISABLE_TELEMETRY=true \
    MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false

WORKDIR /app
COPY requirements.txt /opt/tracking-requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/tracking-requirements.txt \
    && python -m pip check \
    && python -m pip freeze > /opt/tracking-requirements-resolved.txt
COPY . /app/src/tracking/
WORKDIR /tracking
CMD ["mlflow", "server"]
