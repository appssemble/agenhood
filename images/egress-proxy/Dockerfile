# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

# Non-root for the same reason the agents are non-root.
# Use a unique name to avoid collision with any existing system user.
RUN useradd -u 1001 -m egressproxy

WORKDIR /app
COPY proxy/ /app/proxy/

USER egressproxy
EXPOSE 8888
ENV EGRESS_LISTEN_HOST=0.0.0.0 \
    EGRESS_LISTEN_PORT=8888 \
    EGRESS_DENYLIST=""
ENTRYPOINT ["python", "-m", "proxy"]
