# EOIR API

An API for <https://acis.eoir.justice.gov>. Not official, for personal use only.

## Warning: no public access

I run my own instance of this, but access is closed. If you need this for your own automation projects, you'll need to host this on your own.

This isn't built for scale. It's meant to run as a single process with headed Chrome (headless won't work). Concurrent requests are queued. Lookups are pretty slow (several seconds).

## Usage

```bash
curl -H "x-key: $API_SECRET" \
  "http://127.0.0.1:8001/cases/123456789?nationality=venezuela"
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
# creates .env, which should be edited to set API_SECRET
```

Run the dev server:

```
mise serve
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

Must run on a host machine with Google Chrome (cannot use headless).

Run the server with:

```
mise start
```

## License

Copyright (C) Steven Loria. Licensed under the GNU Affero General Public
License, version 3 or later. See [LICENSE](LICENSE).

Run this privately however you like (including commercially). If you
modify it and let other people reach it over a network, you'll need
to provide users your modified source code.
