#!/usr/bin/env bash
# 在 macOS 上构建 .app；GitHub Actions 里也是直接调用这个脚本。
# 本地用法：bash build/build-macos.sh
set -euo pipefail

APP_NAME="${APP_NAME:-IconStudio}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> 构建 $APP_NAME"
python3 -VV
echo "==> 架构：$(uname -m)"

echo "==> 安装依赖"
python3 -m pip install --upgrade pip >/dev/null
python3 -m pip install -r requirements.txt

echo "==> 依赖自检"
python3 - <<'PY'
import PIL
import PyQt6.QtCore

print(f"   Pillow {PIL.__version__} / PyQt6 {PyQt6.QtCore.PYQT_VERSION_STR} / Qt {PyQt6.QtCore.QT_VERSION_STR}")
PY

echo "==> 生成 .icns 图标"
python3 build/make_icns.py --force || echo "⚠️  图标生成失败，改用默认图标继续"

echo "==> PyInstaller"
rm -rf dist .build-work
python3 -m PyInstaller --noconfirm --clean --distpath dist --workpath .build-work build/app.spec

APP="dist/$APP_NAME.app"
if [ ! -d "$APP" ]; then
  echo "❌ 没有生成 $APP，看看上面 PyInstaller 的报错"
  exit 1
fi

# Apple 芯片上未签名的可执行文件跑不起来；没有证书就用 ad-hoc 签名
if [ -n "${MACOS_SIGN_IDENTITY:-}" ]; then
  echo "==> 正式签名：$MACOS_SIGN_IDENTITY"
  codesign --force --deep --options runtime --timestamp \
    --entitlements build/entitlements.plist \
    --sign "$MACOS_SIGN_IDENTITY" "$APP"
else
  echo "==> ad-hoc 签名（本机自用足够）"
  codesign --force --deep --sign - "$APP" || true
fi

codesign -dv --verbose=2 "$APP" 2>&1 | head -n 12 || true
du -sh "$APP" || true
echo "✅ 完成：$APP"
