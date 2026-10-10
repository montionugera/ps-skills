#!/usr/bin/env bash
# Builds the engine for every machine type a place can run on. The same
# version must be installed in every place. This script installs nothing.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VERSION="${VERSION:-0.2.0-sync+$(git rev-parse --short HEAD)}"
OUT=bin/release
mkdir -p "$OUT"

for target in darwin/amd64 darwin/arm64 linux/amd64; do
    os="${target%/*}"
    arch="${target#*/}"
    CGO_ENABLED=0 GOOS="$os" GOARCH="$arch" go build -trimpath \
        -ldflags "-X main.version=$VERSION" \
        -o "$OUT/vault-engine-$os-$arch" ./cmd/vault-engine
    echo "built $OUT/vault-engine-$os-$arch"
done

( cd "$OUT" && shasum -a 256 vault-engine-darwin-amd64 vault-engine-darwin-arm64 vault-engine-linux-amd64 > SHA256SUMS )
echo "version $VERSION"
