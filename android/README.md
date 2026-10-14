# AYO Payment Helper (Android, v2)

Reads Easypaisa "Received" notifications and forwards them to your AYO gateway. Rebuilt UI with
a live dashboard (today's total, payment history with search), a health checklist, and a
foreground "payment watch" service so payments keep syncing even when the app is swiped away.

## Download / build the APK
This repo builds the APK automatically with **GitHub Actions** (`.github/workflows/build-apk.yml`).
After it runs, the signed APK is attached to the **`apk-v2` release** and as a workflow artifact — open
that on your phone and install it.

Build locally instead (JDK 17 + Android SDK platform 35 / build-tools 35.0.0):

    export ANDROID_SDK_ROOT=/path/to/android-sdk
    bash android/build.sh      # -> android/AYO-Payment-Helper.apk

## Reliability (never miss a payment)
- Foreground service with an ongoing notification keeps the process alive.
- `onTaskRemoved` restarts the service when the app is swiped from Recents.
- Boot / package-replaced receiver restarts capture after a reboot or update.
- JobScheduler retries uploads with backoff; failed items stay for manual retry.
- In-app checklist nudges you to grant Notification Access and disable battery optimization.

No app can survive a manual **Force stop** or some OEMs' aggressive task killers, so the gateway
dashboard still supports reconciling against Easypaisa history and manual approval.
