# Changelog

## [3.0.0](https://github.com/sloria/eoir-api/compare/acis-browser-v2.0.0...acis-browser-v3.0.0) (2026-09-08)


### ⚠ BREAKING CHANGES

* **acis-browser:** `AcisBrowser.idle_timeout` and `close_if_idle()` are removed. Callers decide when to close using `last_used`  `close()` now waits for an in-progress lookup.

### Refactors

* **acis-browser:** move idle handling to callers ([#24](https://github.com/sloria/eoir-api/issues/24)) ([aa86d75](https://github.com/sloria/eoir-api/commit/aa86d753b76743f3f710b39b3e5c8f907a58454c))

## [2.0.0](https://github.com/sloria/eoir-api/compare/acis-browser-v1.0.0...acis-browser-v2.0.0) (2026-09-05)


### ⚠ BREAKING CHANGES

* **acis-browser:** normalize_a_number, redact, Nationality, get_by_code, resolve, InvalidANumberError, and UnknownNationalityError moved to acis-core.

### Features

* **acis-browser:** import reference data from acis-core ([4deced1](https://github.com/sloria/eoir-api/commit/4deced122072b4abdad62981e294b323df530539))

## 1.0.0 (2026-09-05)


### Refactors

* factor out acis-browser into its own package ([#17](https://github.com/sloria/eoir-api/issues/17)) ([01c30f0](https://github.com/sloria/eoir-api/commit/01c30f01ccd9553331f00fdd2cbc72c8a2126fed))
