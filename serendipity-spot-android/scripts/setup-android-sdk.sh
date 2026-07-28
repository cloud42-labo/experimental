#!/bin/bash
# Claude Code の Cloud environment 設定にある "Setup script" 欄に貼り付けて使う。
#
# 前提: 同じ環境の Network access を Custom にして dl.google.com を許可しておくこと。
# Android SDK も Google Maven も配布元が dl.google.com なので、許可がないと必ず失敗する。
#
# Setup script は非ゼロ終了するとセッションごと起動失敗するため、
# 個々のコマンドは失敗しても止めず、最後に必ず exit 0 する。

set -u

SDK_ROOT=/opt/android-sdk
# cmdline-tools のリビジョン。新しい番号は https://developer.android.com/studio#command-line-tools-only
CMDLINE_TOOLS_ZIP=commandlinetools-linux-13114758_latest.zip

if ! command -v unzip >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq unzip
fi

if [ ! -d "$SDK_ROOT/cmdline-tools/latest" ]; then
  mkdir -p "$SDK_ROOT/cmdline-tools"
  if curl -fsSL -o /tmp/cmdline-tools.zip \
      "https://dl.google.com/android/repository/${CMDLINE_TOOLS_ZIP}"; then
    unzip -q /tmp/cmdline-tools.zip -d "$SDK_ROOT/cmdline-tools"
    mv "$SDK_ROOT/cmdline-tools/cmdline-tools" "$SDK_ROOT/cmdline-tools/latest"
    rm -f /tmp/cmdline-tools.zip
  else
    echo "cmdline-tools を取得できなかった。dl.google.com が許可されているか確認すること。" >&2
  fi
fi

export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="$SDK_ROOT/cmdline-tools/latest/bin:$PATH"

if command -v sdkmanager >/dev/null 2>&1; then
  yes | sdkmanager --licenses >/dev/null 2>&1 || true
  sdkmanager --install "platform-tools" "platforms;android-35" "build-tools;35.0.0" || true
fi

# 以降のシェル（Claude が叩く bash を含む）にも通す
cat > /etc/profile.d/android-sdk.sh <<EOF
export ANDROID_HOME=$SDK_ROOT
export ANDROID_SDK_ROOT=$SDK_ROOT
export PATH=\$PATH:$SDK_ROOT/cmdline-tools/latest/bin:$SDK_ROOT/platform-tools
EOF

exit 0
