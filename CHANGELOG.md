# Changelog

## [1.0.0](https://github.com/sloria/eoir-api/compare/eoir-api-v1.0.0...eoir-api-v1.0.0) (2026-11-21)


### ⚠ BREAKING CHANGES

* simplify error object implmentation ([#90](https://github.com/sloria/eoir-api/issues/90))
* RFC 9457 error objects ([#88](https://github.com/sloria/eoir-api/issues/88))
* switch to POST for lookups ([#67](https://github.com/sloria/eoir-api/issues/67))
* use file-based config ([#62](https://github.com/sloria/eoir-api/issues/62))
* **acis-browser:** `AcisBrowser.idle_timeout` and `close_if_idle()` are removed. Callers decide when to close using `last_used`  `close()` now waits for an in-progress lookup.
* **acis-browser:** normalize_a_number, redact, Nationality, get_by_code, resolve, InvalidANumberError, and UnknownNationalityError moved to acis-core.
* change header key to x-api-key

### Features

* **acis-browser:** add AcisBrowser.is_running ([#58](https://github.com/sloria/eoir-api/issues/58)) ([84888fe](https://github.com/sloria/eoir-api/commit/84888fe2c5af7b900c3470c43054607bb7c17637))
* **acis-browser:** allow passing a proxy to AcisBrowser ([#54](https://github.com/sloria/eoir-api/issues/54)) ([0bd2d19](https://github.com/sloria/eoir-api/commit/0bd2d19207356f109fe3dcf5821bf3693b09cef8))
* **acis-browser:** default lookup_attempts to 1 ([#31](https://github.com/sloria/eoir-api/issues/31)) ([430da0f](https://github.com/sloria/eoir-api/commit/430da0f943924cb2b0f0700fb60c67187fc61727))
* **acis-browser:** import reference data from acis-core ([4deced1](https://github.com/sloria/eoir-api/commit/4deced122072b4abdad62981e294b323df530539))
* **acis-browser:** purge local storage etc ([#98](https://github.com/sloria/eoir-api/issues/98)) ([dfe1cd7](https://github.com/sloria/eoir-api/commit/dfe1cd7f39a21a5b684b5ce71f6ca3a33b3afb13))
* **acis-browser:** return error early when captcha is encountered ([#63](https://github.com/sloria/eoir-api/issues/63)) ([e5a5f20](https://github.com/sloria/eoir-api/commit/e5a5f20ad7cc91f852b07099be0e62c423833d31))
* **acis-core:** add all_nationalities ([#39](https://github.com/sloria/eoir-api/issues/39)) ([2c04f36](https://github.com/sloria/eoir-api/commit/2c04f363244178696736b12354f24062f4af997e))
* **acis-core:** add Case and diff API for computing case changes ([#50](https://github.com/sloria/eoir-api/issues/50)) ([d911e8c](https://github.com/sloria/eoir-api/commit/d911e8cc5f9bc462507cb80c98445ec07f7e444f))
* **acis-core:** add package ([cd19f50](https://github.com/sloria/eoir-api/commit/cd19f5035bb5fbb953f37a50bc9fa6cc0361c982))
* add client_ip_header setting for login rate limiting ([#93](https://github.com/sloria/eoir-api/issues/93)) ([fbfb5cb](https://github.com/sloria/eoir-api/commit/fbfb5cbe7fe2b37341a261706eab5d245ed0abc5))
* add explicit browser group config ([#65](https://github.com/sloria/eoir-api/issues/65)) ([6a5feaa](https://github.com/sloria/eoir-api/commit/6a5feaaccb83760566d3f050c70c79daf3bff803))
* add index route ([#85](https://github.com/sloria/eoir-api/issues/85)) ([f93ae34](https://github.com/sloria/eoir-api/commit/f93ae34da261066dbb68310e6ad017cb1d17c9da))
* add multi-tenant support and portal UI ([#72](https://github.com/sloria/eoir-api/issues/72)) ([6af751e](https://github.com/sloria/eoir-api/commit/6af751e862ee3558f699334fffb7b85800c1890b))
* add per-tenant `max_concurrency` ([#80](https://github.com/sloria/eoir-api/issues/80)) ([3da8a51](https://github.com/sloria/eoir-api/commit/3da8a51b57e2f286ed2fbc5c72a0447df5922dc6))
* change header key to x-api-key ([72ca58d](https://github.com/sloria/eoir-api/commit/72ca58daf5f90941b6ba4f6909604f6d90b27aaf))
* change ok message ([86f2571](https://github.com/sloria/eoir-api/commit/86f257191e44bc2175161b8e0569f682c3c8359c))
* don't store A-numbers (even redacted); send x-request-id ([#83](https://github.com/sloria/eoir-api/issues/83)) ([e19e88d](https://github.com/sloria/eoir-api/commit/e19e88dc2ce0069d4dd6182335e279f2cabc46d1))
* improve error handling and messages ([#69](https://github.com/sloria/eoir-api/issues/69)) ([655a025](https://github.com/sloria/eoir-api/commit/655a025031ddf98b737cabaa5a5554426735a3d6))
* **portal:** change error message for captcha errors in portal ([333ec64](https://github.com/sloria/eoir-api/commit/333ec6425437392d710c474fead23f32ca74bc28))
* **portal:** various polish ([#91](https://github.com/sloria/eoir-api/issues/91)) ([78e08f4](https://github.com/sloria/eoir-api/commit/78e08f4699ac2ac55325e8844e170bc2c178f114))
* remove nat code from logs ([#86](https://github.com/sloria/eoir-api/issues/86)) ([19ec252](https://github.com/sloria/eoir-api/commit/19ec2520b85e2047ac868c3dddffe490cd31b06b))
* replace CHROME_PROXIES with BROWSERS list; direct browser is explicit ([5e09c40](https://github.com/sloria/eoir-api/commit/5e09c401f6b32704c84776ca37cb8565853e6d49))
* retry on the group challenged longest ago ([#79](https://github.com/sloria/eoir-api/issues/79)) ([2ec3f26](https://github.com/sloria/eoir-api/commit/2ec3f26d19d68d74d70d0a6c210ed7093ccdcf58))
* RFC 9457 error objects ([#88](https://github.com/sloria/eoir-api/issues/88)) ([0b39816](https://github.com/sloria/eoir-api/commit/0b39816d5abd360943df8e07e8916d99898cb135))
* store Chrome profiles in platform user data dir, one per browser ([7acf900](https://github.com/sloria/eoir-api/commit/7acf90030e71af1cffe382c0e8fa21d71d969a4c))
* support multiple browsers over proxies ([#57](https://github.com/sloria/eoir-api/issues/57)) ([6bc2a10](https://github.com/sloria/eoir-api/commit/6bc2a10d9874d8be9fcd10aeb74899289c22691a))
* use file-based config ([#62](https://github.com/sloria/eoir-api/issues/62)) ([5e5db7d](https://github.com/sloria/eoir-api/commit/5e5db7dadc985cb87ebf52ec737cff6b180996a0))


### Bug Fixes

* **acis-browser:** handle slow networks by waiting for app hydration and hCaptcha load ([#37](https://github.com/sloria/eoir-api/issues/37)) ([6ddbe33](https://github.com/sloria/eoir-api/commit/6ddbe331e9a87adb768f78a28b32669eda20e340))
* **acis-browser:** recover from dead driver subprocess ([#28](https://github.com/sloria/eoir-api/issues/28)) ([ade421a](https://github.com/sloria/eoir-api/commit/ade421a7f30125164cee3501a0d0c4ddaeae5662))
* **acis-core:** redact uses correct number of asterisks ([#76](https://github.com/sloria/eoir-api/issues/76)) ([fdf1de0](https://github.com/sloria/eoir-api/commit/fdf1de0e937f65716a937d3fe575a75c19934046))
* **acis-core:** reject ambiguous nationality names; accept former country codes ([#94](https://github.com/sloria/eoir-api/issues/94)) ([e05a83a](https://github.com/sloria/eoir-api/commit/e05a83aca502ddf67ed2e53d966aa2ff271785bb))
* add limit to number of browsers used per lookup ([ee4ffb7](https://github.com/sloria/eoir-api/commit/ee4ffb79e2a281ade48c6b398927f9c81af82ffd))
* **deps:** update all non-major dependencies ([#92](https://github.com/sloria/eoir-api/issues/92)) ([a2496e4](https://github.com/sloria/eoir-api/commit/a2496e48298898631d9eec73b0abe3380eeafff2))
* **deps:** update dependency sqlspec to v0.70.0 ([#73](https://github.com/sloria/eoir-api/issues/73)) ([789d284](https://github.com/sloria/eoir-api/commit/789d284acd24ca3ed17c2d04f9323b2764dedcd1))
* **deps:** update dependency sqlspec to v0.71.1 ([#96](https://github.com/sloria/eoir-api/issues/96)) ([14658d4](https://github.com/sloria/eoir-api/commit/14658d47e3e1a9a306cf45c2f6948a89489c5d68))
* don't reuse a dead Chrome context ([#15](https://github.com/sloria/eoir-api/issues/15)) ([4f124aa](https://github.com/sloria/eoir-api/commit/4f124aac54e4d20655ea0a141a5d11e211441551))
* inaccurate error message ([55db8a1](https://github.com/sloria/eoir-api/commit/55db8a13a908dbebd0b4bf16cb046716b50e3fdc))
* make nationality required ([33c025a](https://github.com/sloria/eoir-api/commit/33c025ace5d15644d498f2d9dab93b1f52682e51))
* nationailty option matching ([a5ea6c8](https://github.com/sloria/eoir-api/commit/a5ea6c8bb2017e3250d609992f8e9b76e2899aca))
* only document 'code' for 429 responses ([#89](https://github.com/sloria/eoir-api/issues/89)) ([b81b0cd](https://github.com/sloria/eoir-api/commit/b81b0cd45e150b73fbe0f4830ed6fb926335cba1))
* **portal:** fix pagination; display localized times ([7d596d3](https://github.com/sloria/eoir-api/commit/7d596d3542c0d3ea2cf451a57dcde75d9ba9350e))
* **portal:** singularize 'lookup' ([#78](https://github.com/sloria/eoir-api/issues/78)) ([d173cf9](https://github.com/sloria/eoir-api/commit/d173cf90b6216629634a1885e7839a3866b55796))
* prevent expected CAPTCHA errors from showing up in sentry ([#4](https://github.com/sloria/eoir-api/issues/4)) ([e9af6be](https://github.com/sloria/eoir-api/commit/e9af6be3b25f60e059e4f3982b2ebbe42c0765fa))
* prevent on-disk caching within browser profiles ([#100](https://github.com/sloria/eoir-api/issues/100)) ([39a8f8b](https://github.com/sloria/eoir-api/commit/39a8f8b362c8ccf55243fa0add5627689c59a7b2))
* put browser in cooldown on no_request errors ([278b2fe](https://github.com/sloria/eoir-api/commit/278b2fe6a31c4789280ba17a1c18022fe7772e68))
* **quota:** don't count upstream errors; increase default retention ([ca6dd5d](https://github.com/sloria/eoir-api/commit/ca6dd5d557376bc0d471fba06c3050a0ada8529a))
* type check ([63f4fa6](https://github.com/sloria/eoir-api/commit/63f4fa66664878a144aa180d9ae14e32781bdf64))


### Performance Improvements

* pre-warm pages and intercept case requests (experimental, opt in) ([527f99f](https://github.com/sloria/eoir-api/commit/527f99f5b5cf9321d913f6880c2bd3fef2e0e65e))
* remove unnecessary warm page cap ([#107](https://github.com/sloria/eoir-api/issues/107)) ([83070a6](https://github.com/sloria/eoir-api/commit/83070a6c9e3572e55d56219e573ba8a38d4d2f85))
* skip modal wait when possible ([#104](https://github.com/sloria/eoir-api/issues/104)) ([124eff8](https://github.com/sloria/eoir-api/commit/124eff8e0aa0667f55fe3b25d7a8e4b9b5dc9b2b))


### Documentation

* update docs and match portal style ([#81](https://github.com/sloria/eoir-api/issues/81)) ([b531530](https://github.com/sloria/eoir-api/commit/b53153099d7067c1651643d5e44cb5fe76a79dc1))


### Code Refactoring

* **acis-browser:** move idle handling to callers ([#24](https://github.com/sloria/eoir-api/issues/24)) ([aa86d75](https://github.com/sloria/eoir-api/commit/aa86d753b76743f3f710b39b3e5c8f907a58454c))
* simplify error object implmentation ([#90](https://github.com/sloria/eoir-api/issues/90)) ([357b4f3](https://github.com/sloria/eoir-api/commit/357b4f328e09a120d55b187e75db8c5b35fa9031))
* switch to POST for lookups ([#67](https://github.com/sloria/eoir-api/issues/67)) ([cea625b](https://github.com/sloria/eoir-api/commit/cea625b9733d460c948c795573d806e56dd0a5ac))
