# Veristock Android application

This is the Flutter client for Veristock field operations. The React PWA remains the primary interface for Veristock staff and client administrators.

## Responsibilities

- Field employee authentication and organization selection.
- Camera and barcode scanning.
- Assigned stocktaking tasks and count capture (next implementation slice).
- Controlled offline capture and synchronization (not enabled yet).

The mobile application is a client of the shared FastAPI API. It does not calculate authoritative inventory balances or bypass backend authorization.

## Development

Install Flutter stable, then:

```bash
cd mobile
flutter pub get
flutter analyze
flutter test
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api
```

The default API URL targets a backend running on the host machine when using the Android emulator. For a physical Android device, supply the development machine's LAN address or a deployed HTTPS API URL.

## Authentication

The app uses the existing JSON token endpoints. Access and refresh tokens are stored using platform secure storage. Do not persist tokens in shared preferences, logs or local databases.

## Current scope

The current slice provides login, refresh-token session restoration, organization selection and a working barcode-scanner screen. Stocktake assignment, count submission, encrypted offline task storage and synchronization are not yet implemented.
