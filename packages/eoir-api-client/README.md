# eoir-api-client

Sync and async clients for [eoir-api](https://github.com/sloria/eoir-api).

```python
import eoir_api_client

with eoir_api_client.Client("https://eoir-api.example.com", "my-api-key") as client:
    try:
        result = client.lookup("123456789", "Mexico")
    except eoir_api_client.CaseNotFoundError:
        ...
    except eoir_api_client.RetryLaterError as error:
        ...  # try again in error.retry_after seconds
    else:
        result.case  # acis_core.case.Case object
        result.acis  # raw ACIS payload
```

`eoir_api_client.AsyncClient` has the same interface (`await client.lookup(...)`)
