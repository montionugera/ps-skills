#!/usr/bin/env bash
# Builds the engine for every machine type a place can run on. The same
# version must be installed in every place. This script installs nothing.
#
# The binaries are built and checked in a staging folder first, so a build
# that fails leaves the earlier set in bin/release/ as it was. Moving the new
# set into place is not one atomic step: if that is interrupted, SHA256SUMS is
# missing, and a missing SHA256SUMS means "not a complete set, build again".
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ -z "${VERSION:-}" ]; then
    VERSION="0.2.0-sync+$(git rev-parse --short HEAD)"
    # Uncommitted or untracked files under this folder mean the build is not
    # the commit its version names: say so in the version.
    [ -z "$(git status --porcelain -- .)" ] || VERSION="$VERSION.dirty"
fi
OUT=bin/release
mkdir -p "$OUT"
# A run that was killed outright may have left a staging folder behind. Clear
# what this script owns there: its named files, then the empty folder. Two
# builds at the same time in one folder are not supported.
for old in "$OUT"/.stage.*; do
    [ -d "$old" ] || continue
    rm -f "$old"/vault-engine-* "$old/SHA256SUMS"
    rmdir "$old" 2>/dev/null || true
done
STAGE="$(mktemp -d "$OUT/.stage.XXXXXX")"
# Clears the staging folder on every exit, failed or not (plain files only).
cleanup() {
    rm -f "$STAGE"/vault-engine-* "$STAGE/SHA256SUMS"
    rmdir "$STAGE" 2>/dev/null || true
}
trap cleanup EXIT

names=()
for target in darwin/amd64 darwin/arm64 linux/amd64; do
    os="${target%/*}"
    arch="${target#*/}"
    name="vault-engine-$os-$arch"
    CGO_ENABLED=0 GOOS="$os" GOARCH="$arch" go build -trimpath \
        -ldflags "-X main.version=$VERSION" \
        -o "$STAGE/$name" ./cmd/vault-engine
    # The stamp is looked for in the file itself, so the check also covers a
    # binary this machine cannot run.
    grep -a -q -F -e "$VERSION" "$STAGE/$name" \
        || { echo "build-release: $name does not carry version $VERSION" >&2; exit 1; }
    names+=("$name")
    echo "built $OUT/$name"
done

# The binary for this machine, when there is one, must also say the version.
host="vault-engine-$(go env GOHOSTOS)-$(go env GOHOSTARCH)"
if [ -x "$STAGE/$host" ]; then
    said="$(VAULT_ROOT="$STAGE" "$STAGE/$host" version)"
    [ "$said" = "vault-engine $VERSION" ] \
        || { echo "build-release: $host does not carry version $VERSION (it says: $said)" >&2; exit 1; }
fi

( cd "$STAGE" && shasum -a 256 "${names[@]}" > SHA256SUMS )

# Everything is built and checked. The old checksum file goes first and the
# new one comes last, so an interrupted swap never leaves a checksum file
# beside binaries it does not describe.
rm -f "$OUT/SHA256SUMS"
for name in "${names[@]}"; do
    mv -f "$STAGE/$name" "$OUT/$name"
done
mv -f "$STAGE/SHA256SUMS" "$OUT/SHA256SUMS"
echo "version $VERSION"
