FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DVC_NO_ANALYTICS=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/versioning-requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/versioning-requirements.txt \
    && python -m pip check \
    && python -m pip freeze > /opt/versioning-requirements-resolved.txt
COPY register_reference.py LICENSE /opt/versioning/
WORKDIR /repo
CMD ["python", "-B", "/opt/versioning/register_reference.py"]
