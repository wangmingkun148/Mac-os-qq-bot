#!/bin/zsh
# Build QQChatBridge.app (set APP_OUT to build somewhere else, e.g. for a trial run).
# CODESIGN_IDENTITY names a code-signing certificate (see `security find-identity -v -p codesigning`); the default
# "-" is an ad-hoc signature, which changes on every build and makes macOS forget the Accessibility permission.
set -eu
cd "${0:A:h}"
app="${APP_OUT:-QQChatBridge.app}"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
sources=(Sources/*.swift Sources/UI/*.swift)
common=(-O -debug-prefix-map "$PWD=/QQChatBridge" -target "$(uname -m)-apple-macos14.0" -module-cache-path /tmp/qqchatbridge-swift-cache)
compiler=/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swiftc
sdk=/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
if [[ -x "$compiler" && -d "$sdk" ]]; then
  "$compiler" $common -sdk "$sdk" $sources -o "$app/Contents/MacOS/QQChatBridge"
else
  swiftc $common $sources -o "$app/Contents/MacOS/QQChatBridge"
fi
cp Resources/Fonts/ArkPixel12.otf Resources/Fonts/ArkPixel-OFL.txt "$app/Contents/Resources/"
if [[ -f Resources/AppIcon.icns ]]; then cp Resources/AppIcon.icns "$app/Contents/Resources/"; fi
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>QQChatBridge</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIdentifier</key><string>io.github.wangmingkun148.qqchatbridge</string>
<key>CFBundleName</key><string>QQChatBridge</string>
<key>CFBundleDisplayName</key><string>QQ 聊天 Bot（开源版）</string>
<key>CFBundleVersion</key><string>2</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --sign "${CODESIGN_IDENTITY:--}" "$app"
