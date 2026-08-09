# 05 - GET /{short_code} Redirect Endpoint & HTTP Redirect Semantics

This document explains the design, mechanics, and HTTP semantics of the `GET /{short_code}` redirect endpoint in our URL shortener backend.

---

## 1. What Problem Does This Solve?

When a user or application receives a shortened link (e.g., `https://short.ly/fast01`), their browser or HTTP client navigates to that URL. 

The `GET /{short_code}` endpoint is responsible for:
1. Receiving the short code from the URL path.
2. Searching PostgreSQL for the matching link record.
3. Returning an `HTTP 404 Not Found` if the code does not exist.
4. Incrementing the `click_count` counter for analytics.
5. Instructing the client's browser to immediately navigate to the `original_url` via an HTTP redirect response.

---

## 2. HTTP Redirects: 301 vs. 302 vs. 307

When a server redirects a client, it responds with an HTTP `3xx` status code and a `Location` header containing the destination URL. Choosing the right status code is critical for a URL shortener:

| Status Code | Meaning | Browser Caching Behavior | Click Tracking Impact |
|---|---|---|---|
| **301 Moved Permanently** | The resource has permanently moved to a new URL. | **Aggressively cached** by browsers, proxies, and CDNs indefinitely. | **Breaks Analytics**: On subsequent visits, the browser goes straight to the destination without contacting our server. |
| **302 Found** (or **307 Temporary Redirect**) | The resource resides temporarily at a different URL. | **Not cached** by default (or only very briefly). | **Accurate Analytics**: The browser contacts our server on *every click*, allowing us to increment `click_count`. |

### Why We Use 302 Found (or 307)
We intentionally use **`302 Found`**:
* **Every Click Hits the Server**: Because the browser considers the redirect temporary, it will never skip our backend on future visits.
* **Accurate Metrics**: Every single visit successfully triggers our database counter update (`click_count += 1`).
* **Flexibility**: If the destination URL is ever edited or deactivated in the future, clients will immediately receive the updated destination or a 404, rather than being stuck on a stale cached redirect.

---

## 3. Database Efficiency & Indexing

In `app/models.py`, the `short_code` column is explicitly indexed:
```python
short_code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
```

Because of this B-tree index in PostgreSQL:
* Lookups for `WHERE short_code = :code` execute in logarithmic time $\mathcal{O}(\log N)$, instead of scanning the whole table ($\mathcal{O}(N)$).
* The redirect endpoint remains sub-millisecond fast even with millions of stored URLs.

---

## 4. Request Lifecycle Walkthrough

```
[User clicks https://short.ly/fast01]
                 │
                 ▼
      [FastAPI GET /{short_code}]
                 │
                 ▼
    ┌──────────────────────────┐
    │ SELECT * FROM links      │
    │ WHERE short_code = '...' │
    └────────────┬─────────────┘
                 │
          Record exists?
          /            \
       [No]            [Yes]
        │                │
        ▼                ▼
┌──────────────┐  ┌───────────────────────────┐
│ Return 404   │  │ link.click_count += 1     │
│ Not Found    │  │ await db.commit()         │
└──────────────┘  └──────────────┬────────────┘
                                 │
                                 ▼
                  ┌───────────────────────────┐
                  │ Return HTTP 302 Found     │
                  │ Header: Location -> Target│
                  └──────────────┬────────────┘
                                 │
                                 ▼
           [Browser navigates to original URL]
```

---

## 5. Summary of Created Components

* **Route Implementation**: Added `GET /{short_code}` to [app/routers/links.py](../app/routers/links.py) using `RedirectResponse(url=link.original_url, status_code=302)`.
* **Automated Tests**: Added [tests/test_redirect.py](../tests/test_redirect.py) verifying:
  * Redirects return HTTP 302 with the exact `Location` header.
  * Consecutive visits increment `click_count` in PostgreSQL from 0 to 1, then to 2.
  * Non-existent short codes return HTTP 404 with a structured error detail.
