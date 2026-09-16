# Changelog

## [3.1.0](https://github.com/sloria/eoir-api/compare/acis-browser-v3.0.1...acis-browser-v3.1.0) (2026-09-16)


### Features

* **acis-browser:** default lookup_attempts to 1 ([#31](https://github.com/sloria/eoir-api/issues/31)) ([430da0f](https://github.com/sloria/eoir-api/commit/430da0f943924cb2b0f0700fb60c67187fc61727))

## [3.0.1](https://github.com/sloria/eoir-api/compare/acis-browser-v3.0.0...acis-browser-v3.0.1) (2026-09-15)


### Bug Fixes

* **acis-browser:** recover from dead driver subprocess ([#28](https://github.com/sloria/eoir-api/issues/28)) ([ade421a](https://github.com/sloria/eoir-api/commit/ade421a7f30125164cee3501a0d0c4ddaeae5662))

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
