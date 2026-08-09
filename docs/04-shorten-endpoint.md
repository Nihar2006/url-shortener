# 04 - POST /shorten Endpoint & Collision Strategy

This document explains the design, mechanics, and implementation of the `POST /shorten` endpoint in our URL shortener backend.

---

## 1. What Problem Does This Solve?

A URL shortener's core job is to turn long, unwieldy URLs (e.g., `https://example.com/products/electronics/item-987234?ref=newsletter&campaign=summer_sale`) into short, uniform codes (e.g., `aB3x9Q`).

The `POST /shorten` endpoint provides an API for clients to:
1. Submit an original URL in a JSON payload.
2. Validate that the URL is syntactically well-formed.
3. Automatically generate a unique, compact identifier (`short_code`).
4. Persist the link in PostgreSQL.
5. Return the generated `short_code` to the caller with a `201 Created` status code.

---

## 2. API Contract

### Request
* **HTTP Method**: `POST`
* **Path**: `/shorten`
* **Headers**: `Content-Type: application/json`
* **Body**:
```json
{
  "url": "https://fastapi.tiangolo.com/tutorial/"
}
```

### Response
* **Status Code**: `201 Created`
* **Body**:
```json
{
  "short_code": "k9xL2p"
}
```

### Validation Error
If the caller provides an invalid URL (e.g. `"url": "not-a-link"`), Pydantic automatically intercepts the request and responds with:
* **Status Code**: `422 Unprocessable Entity`

---

## 3. How Short Codes Are Generated

### The Alphabet: Base62
We generate short codes using **Base62**, which consists of:
* 26 lowercase English letters (`a`–`z`)
* 26 uppercase English letters (`A`–`Z`)
* 10 numerical digits (`0`–`9`)

**Why Base62?**
* **URL-Safe**: None of these characters need percent-encoding (unlike `/`, `+`, `=`, or `?`).
* **Compact**: With 62 characters per position, a short string packs a massive number of permutations.

### Permutations & Keyspace
With a code length of **6 characters**:
$$\text{Total Combinations} = 62^6 = 56,800,235,584 \quad (\approx 56.8\text{ billion})$$

This is more than enough capacity for high-scale applications while keeping URLs very short (e.g. `short.ly/k9xL2p`).

### Cryptographic Randomness (`secrets` vs `random`)
We use Python's built-in `secrets` module (`secrets.choice`) instead of `random.choice`:
* `random` uses the Mersenne Twister algorithm, which is pseudo-random and predictable if an attacker observes a sequence of outputs.
* `secrets` accesses the operating system's cryptographically secure pseudo-random number generator (CSPRNG), making it impossible for someone to guess or harvest links sequentially.

---

## 4. Understanding & Handling Collisions

### What is a Collision?
A collision occurs when the code generator randomly produces a `short_code` that is already stored in the database for another link.

### Why Do Collisions Happen?
1. **The Birthday Paradox**: In any random key generation system, as the database fills up with millions of rows, the mathematical probability of two random picks being identical increases.
2. **Concurrency / Race Conditions**: Two users might hit the `/shorten` endpoint at the exact same millisecond. Even if you checked the database before generating, both requests might see the code as available and try to insert it simultaneously (a classic *Time-of-Check to Time-of-Use / TOCTOU* bug).

### How We Handle Collisions

Instead of doing an extra `SELECT` query beforehand, we use an **Optimistic Retry Pattern** backed by **PostgreSQL's Unique Constraint**:

```
[Incoming Request]
        │
        ▼
┌───────────────────────────────┐
│ Generate 6-char random code   │ ◄─────────────────────────┐
└───────────────┬───────────────┘                           │
                │                                           │
                ▼                                           │
┌───────────────────────────────┐                           │
│ Open Nested Savepoint         │                           │
│ (SAVEPOINT sa_savepoint_N)    │                           │
└───────────────┬───────────────┘                           │
                │                                           │
                ▼                                           │
┌───────────────────────────────┐                           │
│ Attempt DB Insert & Flush     │                           │
└───────────────┬───────────────┘                           │
                │                                           │
        Success or Conflict?                                │
        /               \                                   │
   [Success]        [IntegrityError (Collision)]            │
       │                         │                          │
       ▼                         ▼                          │
┌──────────────┐    ┌──────────────────────────────────┐    │
│ Commit DB &  │    │ Rollback to Savepoint            │────┘ (Retry up to 5 times)
│ Return 201   │    │ (Session stays clean and usable) │
└──────────────┘    └──────────────────────────────────┘
```

#### Why Savepoints (`db.begin_nested()`)?
In PostgreSQL and SQLAlchemy async sessions, when a query fails with a constraint violation, PostgreSQL immediately puts the transaction into an error state (`InFailedSqlTransactionError`). 

By wrapping each attempt inside `async with db.begin_nested():`, SQLAlchemy creates a SQL `SAVEPOINT`. If an `IntegrityError` occurs:
1. PostgreSQL rolls back only to that savepoint (`ROLLBACK TO SAVEPOINT`).
2. The overall database session remains completely healthy.
3. The loop seamlessly generates a new code and tries again.

#### Fail-Safe Limit
If after 5 attempts all generated codes collide (statistically negligible unless the keyspace is nearly exhausted), the API raises an `HTTP 500 Internal Server Error` rather than hanging in an infinite loop.

---

## 5. Summary of Created Components

| File | Purpose |
|---|---|
| [app/schemas.py](../app/schemas.py) | Pydantic validation schemas (`URLShortenRequest`, `URLShortenResponse`) |
| [app/utils.py](../app/utils.py) | Base62 random short code generator using `secrets` |
| [app/routers/links.py](../app/routers/links.py) | `POST /shorten` route with savepoint-based retry logic |
| [app/main.py](../app/main.py) | Main FastAPI application instance and router registration |
| [tests/test_shorten.py](../tests/test_shorten.py) | Automated test suite covering success, validation, retry, and exhaustion |
