#!/usr/bin/env bash
# Builds and signs AYO-Payment-Helper.apk. Needs JDK 17+ and Android SDK (platform 35, build-tools 35.0.0).
set -euo pipefail
cd "$(dirname "$0")"
: "${ANDROID_SDK_ROOT:?Set ANDROID_SDK_ROOT to your Android SDK}"
BT="${ANDROID_SDK_ROOT}/build-tools/35.0.0"
JAR="${ANDROID_SDK_ROOT}/platforms/android-35/android.jar"
rm -rf build && mkdir -p build/gen build/classes build/dex
# 1) parser self-test (pure Java, no Android)
mkdir -p build/test && javac -d build/test src/com/ayo/paymenthelper/PaymentParser.java tests/ParserTest.java && java -cp build/test ParserTest
# 2) resources -> R.java + compiled resources
"$BT/aapt2" compile --dir res -o build/res.zip
"$BT/aapt2" link -o build/base.apk --manifest AndroidManifest.xml -I "$JAR" --java build/gen --min-sdk-version 26 --target-sdk-version 35 build/res.zip
# 3) compile Java
find src build/gen -name '*.java' > build/srcs.txt
javac -encoding UTF-8 --release 8 -classpath "$JAR" -d build/classes @build/srcs.txt
# 4) dex
"$BT/d8" --lib "$JAR" --min-api 26 --release --output build/dex build/classes
# 5) add dex into the apk
( cd build/dex && zip -q ../base.apk classes.dex )
# 6) align + sign
"$BT/zipalign" -f -p 4 build/base.apk build/aligned.apk
if [ ! -f release.jks ]; then
  keytool -genkeypair -keystore release.jks -alias ayo -keyalg RSA -keysize 3072 -validity 10000 \
    -storepass ayo12345 -keypass ayo12345 -dname "CN=AYO Payment Helper, O=AYO, C=PK"
fi
"$BT/apksigner" sign --ks release.jks --ks-key-alias ayo --ks-pass pass:ayo12345 --out AYO-Payment-Helper.apk build/aligned.apk
"$BT/apksigner" verify --verbose AYO-Payment-Helper.apk
echo "APK ready: $(pwd)/AYO-Payment-Helper.apk"
