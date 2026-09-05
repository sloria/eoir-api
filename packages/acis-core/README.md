# acis-core

Reference data and utilities (A-Number normalization, `Outcome` classification of ACIS responses) shared by ACIS clients.

```python
from acis_core.nationalities import get_by_code, resolve

get_by_code("mx")  # Nationality(code='MX', name='MEXICO')
resolve("Mexico")  # same; accepts a code or a name
```
