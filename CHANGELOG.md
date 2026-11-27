# Changelog

## [2.1.0](https://github.com/sloria/eoir-api/compare/eoir-api-v2.0.0...eoir-api-v2.1.0) (2026-11-27)


### Features

* **portal:** filter lookups by status ([9cae9d2](https://github.com/sloria/eoir-api/commit/9cae9d23f5513e3e28d9a3bb22a60690339be681))
* **portal:** record lookups rejected during captcha cooldown ([e870b10](https://github.com/sloria/eoir-api/commit/e870b109f433be90f101204a2285bd726a87bfed))
* **portal:** record rejected lookups ([ae44293](https://github.com/sloria/eoir-api/commit/ae442932f3a925ec0b73ba82f11cb04963ce6566))
* **portal:** show request id on lookups ([80c4989](https://github.com/sloria/eoir-api/commit/80c49890bc65847cbba4d3dd949fc1d2fb3add43))


### Bug Fixes

* **portal:** trim timestamp tooltip to seconds ([0949c45](https://github.com/sloria/eoir-api/commit/0949c45ae86bc1fd0316487fd58ae76ade6ef2b2))
* **portal:** wrap date filter labels with their inputs ([c103b1b](https://github.com/sloria/eoir-api/commit/c103b1bb44d3fa8d2b359885099f3e197c99a75c))

## [2.0.0](https://github.com/sloria/eoir-api/compare/eoir-api-v1.3.0...eoir-api-v2.0.0) (2026-11-27)


### ⚠ BREAKING CHANGES

* return errors as RFC 9457 problems with a code on 404s

### Features

* **eoir-api-client:** expose error code ([df29bca](https://github.com/sloria/eoir-api/commit/df29bcafadbe206c1dd5cbb5d3fd49a7670ad4d0))
* return errors as RFC 9457 problems with a code on 404s ([0c297d7](https://github.com/sloria/eoir-api/commit/0c297d7454846d27e636d6421dd6f94a68f97ef2))


### Bug Fixes

* evict cache on write to avoid memory leak ([79e48bc](https://github.com/sloria/eoir-api/commit/79e48bc6f244e9797495923651bfd16e1644125f))
* more config validation (duplicate tenants, out of bounds) ([b96e628](https://github.com/sloria/eoir-api/commit/b96e6282ed9ce3345a89d34f1b0cfab607351ca3))


### Documentation

* document errors ([05a4631](https://github.com/sloria/eoir-api/commit/05a46313f7421031a31450a1da4a369d32a9ac1e))

## [1.3.0](https://github.com/sloria/eoir-api/compare/eoir-api-v1.2.0...eoir-api-v1.3.0) (2026-11-26)


### Features

* add favicon ([#137](https://github.com/sloria/eoir-api/issues/137)) ([72ac21d](https://github.com/sloria/eoir-api/commit/72ac21da085dc0743048bc1317beedc7874e7afa))


### Dependencies

* lock file maintenance ([#141](https://github.com/sloria/eoir-api/issues/141)) ([6d29032](https://github.com/sloria/eoir-api/commit/6d29032da7bd6a9e6b021b1980c0ae049d5cecb5))

## [1.2.0](https://github.com/sloria/eoir-api/compare/eoir-api-v1.1.0...eoir-api-v1.2.0) (2026-11-24)


### Features

* add eoir-api-client ([#131](https://github.com/sloria/eoir-api/issues/131)) ([ec982ed](https://github.com/sloria/eoir-api/commit/ec982ede05ef90e4838c3602784202f5d7ed01d1))


### Documentation

* **api:** document official Python client ([#135](https://github.com/sloria/eoir-api/issues/135)) ([5e65425](https://github.com/sloria/eoir-api/commit/5e654258421efaccace1b3e631e356c06f2ff25f))

## [1.1.0](https://github.com/sloria/eoir-api/compare/eoir-api-v1.0.2...eoir-api-v1.1.0) (2026-11-23)


### Features

* rename AcisBrowser/AcisError to ACISBrowser/ACISError ([0a992f1](https://github.com/sloria/eoir-api/commit/0a992f15b76b7bb9329846644d0f001a3f2d8d83))

## [1.0.2](https://github.com/sloria/eoir-api/compare/eoir-api-v1.0.1...eoir-api-v1.0.2) (2026-11-21)


### Documentation

* **api:** document ACISPayload in the API ([e16d6aa](https://github.com/sloria/eoir-api/commit/e16d6aa720ebdd62a5ad2cf12c8dede7ae08c165))

## [1.0.1](https://github.com/sloria/eoir-api/compare/eoir-api-v1.0.0...eoir-api-v1.0.1) (2026-11-21)


### Documentation

* **api:** add additional OAI docs ([#113](https://github.com/sloria/eoir-api/issues/113)) ([45d1163](https://github.com/sloria/eoir-api/commit/45d1163651ada80d6c87ab150c5b7fee0a15c414))
