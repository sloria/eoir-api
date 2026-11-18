# EOIR API

An API for <https://acis.eoir.justice.gov>. Not official.

## Warning: no public access

I run my own instance of this, but access is closed. If you need this for your own automation projects, you'll need to host this on your own.

## Usage

```bash
curl -H "x-api-key: $API_KEY" \
  --json '{"a_number": "123456789", "nationality": "venezuela"}' \
  http://127.0.0.1:8001/cases/lookup
```

```json
{
  "a_number": "123456789",
  "nationality": {
    "code": "VE",
    "name": "VENEZUELA"
  },
  "retrieved_at": "2026-07-29T03:08:14.963Z",
  "cached": true,
  "acis": {
    "Language": "EN",
    "Data": {
      "AlienName": "DOE, JANE",
      "CaseID": 10000001,
      "ClockStatus": "R",
      "ElapsedDays": "543",
      "LatestHearingDate": "2026-08-06T00:00:00",
      "LatestHearingTime": "8:30 AM",
      "...": "..."
    },
    "Proceeding": {
      "CaseType": "RMV",
      "BaseCityCode": "NYC",
      "HearingLocationAddress": "NEW YORK CITY, NEW YORK|26 FEDERAL PLZ, 12TH FL RM1237|NEW YORK, NY 10278",
      "...": "..."
    },
    "Schedule": {
      "AdjDate": "2026-08-06T00:00:00",
      "AdjTime": "8:30 AM",
      "HearingMedium": "P",
      "IJ_Name": "Roe, Alex",
      "IJ_WebExURLLink": "https://eoir.webex.com/meet/IJ.Roe",
      "...": "..."
    },
    "Appeal": { "...": "..." },
    "Reopen": { "...": "..." },
    "MTR": { "...": "..." }
  }
}
```

## Development

Initial setup:

```
mise setup
```

This creates `hub.toml`, `runner.toml` and `.env`. Fill in API_KEY, PORTAL_SECRET and RUNNER_TOKEN in .env

All settings are documented in [hub.example.toml](hub.example.toml) and [runner.example.toml](runner.example.toml).

Run the dev server (runs hub and runner components simultaneously):

```
mise dev
```

Tests and linting:

```
mise test
mise lint
mise typecheck
```

Run live tests against the ACIS site (excluded from the default run and CI):

```bash
EOIR_TEST_A_NUMBER=... EOIR_TEST_NATIONALITY=... mise run test:live
```

## Deployment

eoir-api has two components:

- Hub (`eoir-api hub`): the API server. Configured by `hub.toml`
- Runners (`eoir-api runner`): run browsers and perform lookups for the hub over HTTP. Configured by `runner.toml`.

### Hub

#### Directly

```bash
uv run --frozen --no-dev eoir-api hub --config /path/to/hub.toml
```

#### Docker

```bash
docker build -t eoir-api .
docker run -v ./hub.toml:/config/hub.toml:ro -v eoir-api-data:/data -p 8001:8001 eoir-api
```

It writes only to `/data`. Set `[server] host = "0.0.0.0"`.

### Runner

Needs a host with Google Chrome and a GUI session (cannot use headless).

```bash
uv run --frozen --no-dev eoir-api runner --config /path/to/runner.toml
```

## License

Copyright (C) Steven Loria. Licensed under the GNU Affero General Public
License, version 3 or later. See [LICENSE](LICENSE).

Run this privately however you like (including commercially). If you
modify it and let other people reach it over a network, you'll need
to disclose your changes. Please contribute patches back!
