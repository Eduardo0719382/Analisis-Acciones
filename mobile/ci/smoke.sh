#!/usr/bin/env bash
# Installs the APK on the CI emulator, opens it and checks that the first screen appears.
set -uo pipefail
mkdir -p smoke
APK=$(ls dist/*.apk | head -1)
TOOLS="$ANDROID_HOME/build-tools/$(ls "$ANDROID_HOME/build-tools" | sort -V | tail -1)"
PKG=$("$TOOLS/aapt" dump badging "$APK" | sed -n "s/package: name='\([^']*\)'.*/\1/p")
echo "APK: $APK  package: $PKG"
adb install -r "$APK" || exit 1
adb logcat -c
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1
ok=0
for i in $(seq 1 36); do
  sleep 5
  adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1 || true
  if adb shell cat /sdcard/ui.xml 2>/dev/null | grep -q "Mi lista"; then
    echo "First screen visible after $((i * 5)) s"
    ok=1
    break
  fi
done
adb shell cat /sdcard/ui.xml > smoke/ui.xml 2>/dev/null || true
adb exec-out screencap -p > smoke/screen.png || true
adb logcat -d > smoke/logcat.txt || true
if ! adb shell pidof "$PKG" >/dev/null; then
  echo "::error::The app is not running (it closed or crashed)."
  grep -E "FATAL|AndroidRuntime|Traceback|Error" smoke/logcat.txt | tail -40
  exit 1
fi
if grep -E "Traceback \(most recent call last\)" smoke/logcat.txt; then
  echo "::error::Python error in the log."
  grep -A 20 "Traceback" smoke/logcat.txt | head -60
  exit 1
fi
if [ "$ok" != 1 ]; then
  echo "::error::The first screen ('Mi lista') did not appear within 3 minutes."
  grep -iE "flet|python|flutter" smoke/logcat.txt | tail -60
  exit 1
fi
echo "Smoke test passed."
