# ADR-001: RTMPS over SRT for ingest

Status: accepted (2026-09-24)

## Context
Kick provides both an RTMPS and an SRT ingest endpoint. TCP to the RTMPS host on 443 and 1935 is
open from this machine; the SRT UDP path could not be confirmed without a full handshake.

## Decision
Publish over RTMPS (`rtmps://fa723fc1b171.global-contribute.live-video.net:443/app/<key>`). SRT stays
a documented fallback only.

## Consequences
- The static ffmpeg build (OpenSSL, no bundled CA path on macOS) needs `-ca_file /etc/ssl/cert.pem
  -tls_verify 1`, added to `stream/run.sh` live mode, plus `SSL_CERT_FILE` in `scripts/env.sh`.
  Certificate verification stays ON.
- Proven end to end: first live push reached Kick, `is_live` within 30 s, HLS probe PASS.
