FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PANDAS_COPY_ON_WRITE=0

WORKDIR /app

COPY requirements-runtime.txt .
RUN python -m pip install --no-cache-dir -r requirements-runtime.txt \
    && python -m pip check \
    && python -m pip freeze > /opt/requirements-resolved.txt

COPY src/ ./src/

CMD ["python", "--version"]
