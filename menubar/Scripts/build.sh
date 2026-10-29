#!/bin/bash
# Builds SystemOne.app, the menu bar front end for clicker.
#
# Adapted from Menu-Bar-Chat's build script: SPM compiles the binary, and this
# assembles the bundle around it by hand and signs it, so neither Xcode nor an
# .xcodeproj is needed. It also writes the path of this checkout into the
# bundle, which is where the app finds clicker (.venv/bin/clicker; run
# `uv sync` first). Building touches nothing but this folder and, the first
# time, the login keychain, where it creates the signing identity.
set -euo pipefail

CONFIG="${CONFIG:-release}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$(cd "$ROOT/.." && pwd)"
APP="$ROOT/SystemOne.app"
NAME="SystemOne"
SIGN_NAME="${SIGN_NAME:-System One Dev}"

cd "$ROOT"

echo "==> swift build -c $CONFIG"
swift build -c "$CONFIG"

BIN_DIR="$(swift build -c "$CONFIG" --show-bin-path)"
BINARY="$BIN_DIR/$NAME"
[ -x "$BINARY" ] || { echo "!! no binary at $BINARY" >&2; exit 1; }

echo "==> assembling $(basename "$APP")"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BINARY" "$APP/Contents/MacOS/$NAME"
cp "$ROOT/Info.plist" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :SystemOneProjectRoot string $PROJECT" "$APP/Contents/Info.plist"

[ -x "$PROJECT/.venv/bin/clicker" ] || echo "   note: no $PROJECT/.venv/bin/clicker yet; run \`uv sync\` in $PROJECT before the first run"

find "$APP" -name '.DS_Store' -delete
xattr -cr "$APP"

# ── Signing identity ──────────────────────────────────────────────────────────
#
# Ad-hoc (`--sign -`) pins the designated requirement to the binary cdhash, which
# changes every rebuild, and macOS then forgets the Accessibility and Screen
# Recording grants. A self-signed Code Signing cert named "System One Dev" keeps
# the identity stable across rebuilds. Menu-Bar-Chat found that Screen Recording
# may still not attach to a certificate with no Apple Team ID; set
# CODESIGN_IDENTITY to an Apple Development identity if it does not.
ensure_dev_identity() {
    if security find-identity -v -p codesigning 2>/dev/null | grep -q "$SIGN_NAME"; then
        return 0
    fi

    echo "==> creating self-signed code-signing identity \"$SIGN_NAME\""
    local tmp
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' RETURN

    cat > "$tmp/cert.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
prompt = no
x509_extensions = v3_code_signing

[req_distinguished_name]
CN = ${SIGN_NAME}

[v3_code_signing]
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
EOF

    openssl req -new -newkey rsa:2048 -x509 -days 3650 -nodes \
        -config "$tmp/cert.cnf" \
        -keyout "$tmp/key.pem" -out "$tmp/cert.pem" >/dev/null 2>&1

    # macOS Security framework still prefers older PKCS#12 ciphers from OpenSSL 3.
    openssl pkcs12 -export \
        -inkey "$tmp/key.pem" -in "$tmp/cert.pem" \
        -out "$tmp/cert.p12" -passout pass:systemonedev \
        -name "$SIGN_NAME" \
        -certpbe PBE-SHA1-3DES -keypbe PBE-SHA1-3DES -macalg sha1 \
        >/dev/null 2>&1 \
        || openssl pkcs12 -export \
            -inkey "$tmp/key.pem" -in "$tmp/cert.pem" \
            -out "$tmp/cert.p12" -passout pass:systemonedev \
            -name "$SIGN_NAME" -legacy \
            >/dev/null 2>&1

    security import "$tmp/cert.p12" \
        -k ~/Library/Keychains/login.keychain-db \
        -P systemonedev \
        -T /usr/bin/codesign \
        -T /usr/bin/security >/dev/null

    # Prefer the identity for codesign without a UI prompt when possible.
    security set-key-partition-list -S apple-tool:,apple:,codesign: \
        -s -k "" ~/Library/Keychains/login.keychain-db >/dev/null 2>&1 || true

    security add-trusted-cert -d -r trustRoot -k ~/Library/Keychains/login.keychain-db \
        "$tmp/cert.pem" 2>/dev/null || true

    if ! security find-identity -v -p codesigning 2>/dev/null | grep -q "$SIGN_NAME"; then
        echo "!! could not create or find identity \"$SIGN_NAME\"" >&2
        echo "   create one in Keychain Access → Certificate Assistant → Create a Certificate:" >&2
        echo "   Name: $SIGN_NAME, Identity Type: Self Signed Root, Certificate Type: Code Signing" >&2
        exit 1
    fi
}

IDENTITY="${CODESIGN_IDENTITY:-}"
if [ -z "$IDENTITY" ]; then
    ensure_dev_identity
    IDENTITY="$SIGN_NAME"
fi

echo "==> codesign ($IDENTITY)"
if ! codesign --force --sign "$IDENTITY" --timestamp=none "$APP"; then
    echo "!! codesign failed with identity \"$IDENTITY\"" >&2
    exit 1
fi

echo "==> built $APP"
