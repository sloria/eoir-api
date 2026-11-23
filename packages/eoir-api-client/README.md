# eoir-api-client

Sync and async clients for [eoir-api](https://github.com/sloria/eoir-api).

## Install

```console
pip install eoir-api-client
```

## Usage

```python
import eoir_api_client

with eoir_api_client.Client("https://eoir-api.example.com", "my-api-key") as client:
    result = client.lookup("123456789", "Mexico")
    # result.case is a Case object
    print(result.case.name)
    # result.acis is the raw ACIS payload
    print(result.acis)
```

## Async usage

`AsyncClient` has the same interface as `Client`.

```python
import asyncio

import eoir_api_client


async def main() -> None:
    async with eoir_api_client.AsyncClient(
        "https://eoir-api.example.com", "my-api-key"
    ) as client:
        result = await client.lookup("123456789", "Mexico")
        print(result.case.name)


asyncio.run(main())
```

## Retries

The client never retries on its own. Handle the following exceptions in your own retry logic:

- `RetryLaterError`: wait `error.retry_after` seconds before retrying the request.
- `ServerError`, `NetworkError`: retry 2-4 times with exponential backoff.

### Blocking example

```python
import time

import eoir_api_client

N_RETRIES = 3


def lookup(a_number: str, nationality: str) -> eoir_api_client.LookupResult:
    with eoir_api_client.Client("https://eoir-api.example.com", "my-api-key") as client:
        for attempt in range(N_RETRIES):
            try:
                return client.lookup(a_number, nationality)
            except eoir_api_client.RetryLaterError as error:
                # Sleep the amount the server tells us to wait
                time.sleep(error.retry_after)
            except (eoir_api_client.ServerError, eoir_api_client.NetworkError):
                # Exponential backoff
                time.sleep(2**attempt)
        return client.lookup(a_number, nationality)
```

### Celery example

```python
import eoir_api_client


@app.task(bind=True, max_retries=3)
def lookup_case(self, a_number: str, nationality: str) -> dict:
    with eoir_api_client.Client("https://eoir-api.example.com", "my-api-key") as client:
        try:
            result = client.lookup(a_number, nationality)
        except eoir_api_client.RetryLaterError as error:
            # Retry after the amount the server tells us to wait
            raise self.retry(exc=error, countdown=error.retry_after)
        except (eoir_api_client.ServerError, eoir_api_client.NetworkError) as error:
            # Exponential backoff
            raise self.retry(exc=error, countdown=2**self.request.retries)
        else:
            return result.acis
```
