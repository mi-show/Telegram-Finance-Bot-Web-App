FROM cgr.dev/chainguard/python:latest-dev@sha256:d2e8bdfbb6ecf99f6098226254e2787f6bb138e3485894c4f9cb5970fed52586 AS base

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

FROM base AS builder

USER root
WORKDIR /build

# Install build dependencies only in the builder stage
RUN apk add --no-cache \
    python-3.13-base \
    python-3.13-base-dev \
    py3.13-pip-base \
    py3.13-setuptools \
    py3.13-wheel \
    py3.13-build-base-dev \
    libffi-dev \
    openssl-dev \
    linux-headers

COPY requirements.txt .
RUN /usr/bin/python3.13 -m pip install --upgrade pip && \
    /usr/bin/python3.13 -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM base

EXPOSE 8000

USER root

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Install runtime system dependencies (Tesseract-OCR with language packs)
RUN apk add --no-cache \
    python-3.13-base \
    py3.13-pip-base \
    py3.13-setuptools \
    tesseract \
    tesseract-eng \
    tesseract-rus \
    tesseract-ukr

# Install pip requirements
WORKDIR /app
COPY requirements.txt .
COPY --from=builder /wheels /wheels
RUN /usr/bin/python3.13 -m pip install --upgrade pip && \
    /usr/bin/python3.13 -m pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && \
    rm -rf /wheels

COPY . /app

RUN mkdir -p /app/data/receipts && \
    chown -R 65532:65532 /app && \
    chmod -R 775 /app/data/receipts
USER 65532

ENTRYPOINT ["/usr/bin/python3.13"]
CMD ["-m", "app"]
