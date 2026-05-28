#!/usr/bin/env bash
# scripts/build_mac.sh
#
# Build, sign, and package Cutyit.app for macOS distribution.
#
# Usage:
#   bash scripts/build_mac.sh              # build + sign + DMG
#   bash scripts/build_mac.sh --notarize   # also notarize (needs env vars below)
#
# Notarization env vars (set in shell or a local .env file):
#   APPLE_ID        your Apple ID email
#   APP_PASSWORD    app-specific password from appleid.apple.com
#
# The Developer ID certificate must be in your login keychain.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

APP_NAME="Cutyit"
VERSION="1.0.0"
BUNDLE_ID="com.lexisvar.cutyit"
DEVELOPER_ID="Developer ID Application: Alexis Alberto Vargas Arteag (H7BGH7JC7G)"
TEAM_ID="H7BGH7JC7G"
DIST_DIR="$REPO_ROOT/dist"
APP_PATH="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/${APP_NAME}-${VERSION}-mac.dmg"
NOTARIZE=0

for arg in "$@"; do
    case "$arg" in
        --notarize) NOTARIZE=1 ;;
        -h|--help)
            sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# Optional: load .env for notarization credentials
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a; source "$REPO_ROOT/.env"; set +a
fi

# ── 1. Clean ─────────────────────────────────────────────────────────────────
echo "→ Cleaning previous build…"
rm -rf "$DIST_DIR" build/

# ── 2. Build .app with PyInstaller ───────────────────────────────────────────
echo "→ Building $APP_NAME.app with PyInstaller…"
.venv/bin/pyinstaller Cutyit.spec --clean --noconfirm

if [[ ! -d "$APP_PATH" ]]; then
    echo "ERROR: $APP_PATH not found after build" >&2
    exit 1
fi

# ── 3. Deep-sign with hardened runtime ───────────────────────────────────────
echo "→ Signing…"

# Sign all embedded dylibs/frameworks first, then the app itself
find "$APP_PATH" -name "*.dylib" -o -name "*.so" -o -name "*.framework" | while read -r f; do
    codesign --force --options runtime \
        --entitlements "$REPO_ROOT/entitlements.plist" \
        --sign "$DEVELOPER_ID" \
        "$f" 2>/dev/null || true
done

codesign --force --options runtime \
    --entitlements "$REPO_ROOT/entitlements.plist" \
    --sign "$DEVELOPER_ID" \
    --deep \
    "$APP_PATH"

codesign --verify --deep --strict --verbose=1 "$APP_PATH"
echo "   Signed OK"

# ── 4. Create DMG ────────────────────────────────────────────────────────────
echo "→ Creating DMG…"

# Simple staging folder with an Applications symlink
STAGING="$(mktemp -d)"
cp -R "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$STAGING" \
    -ov -format UDZO \
    "$DMG_PATH"

rm -rf "$STAGING"

# Sign the DMG
codesign --sign "$DEVELOPER_ID" "$DMG_PATH"
echo "   DMG: $DMG_PATH"

# ── 5. Notarize (optional) ────────────────────────────────────────────────────
if [[ $NOTARIZE -eq 1 ]]; then
    APPLE_ID="${APPLE_ID:-}"
    APP_PASSWORD="${APP_PASSWORD:-}"

    if [[ -z "$APPLE_ID" || -z "$APP_PASSWORD" ]]; then
        echo "ERROR: APPLE_ID and APP_PASSWORD must be set for notarization" >&2
        exit 1
    fi

    echo "→ Submitting for notarization…"
    xcrun notarytool submit "$DMG_PATH" \
        --apple-id "$APPLE_ID" \
        --team-id "$TEAM_ID" \
        --password "$APP_PASSWORD" \
        --wait

    echo "→ Stapling…"
    xcrun stapler staple "$DMG_PATH"
    echo "   Notarized and stapled"
else
    echo "   (skip notarization — pass --notarize to enable)"
fi

echo ""
echo "✓ Done"
echo "  App:  $APP_PATH"
echo "  DMG:  $DMG_PATH"
