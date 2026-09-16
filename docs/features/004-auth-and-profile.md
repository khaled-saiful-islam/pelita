# 004 — Authentication and profile

## What it does

Username/password sign-up and sign-in, an httpOnly session cookie, protected
routes, a profile page for display name, email and password, and a seeded admin
account so `make up` lands on an app you can actually sign into.

## How it works

### The token lives in a cookie the browser cannot read

`POST /api/auth/signin` returns the user in the body and sets the JWT as an
httpOnly cookie. The token never appears in the response body and is never
written to `localStorage`.

This costs one request on page load — "am I signed in?" is answered by calling
`/api/auth/me` rather than by reading storage. In exchange, a successful XSS
cannot walk away with the session. For a template that people will deploy
without reading every line, that is the right side of the trade.

The same token is accepted as `Authorization: Bearer` for scripts and API
clients, which have no cookie jar and no XSS surface.

`SameSite=lax` is what makes CSRF tokens unnecessary: the cookie is not sent on
cross-site POSTs, and the SPA and API are same-origin behind nginx.

### Failed sign-in says one thing

"No such user" and "wrong password" both return *Incorrect username or
password.* Distinguishing them turns the login form into an account enumeration
oracle — an attacker learns which addresses are registered by watching which
error comes back. `test_failed_sign_in_is_indistinguishable` asserts all three
failure paths produce the identical message.

### Passwords

bcrypt via the `bcrypt` package directly, not passlib — passlib has a
long-standing incompatibility with bcrypt 4.x and adds nothing here.

bcrypt silently truncates at 72 bytes. Pelita rejects longer passwords instead,
because a password where only the first 72 bytes matter, without anyone being
told, is worse than an error message.

`verify_password` never raises. A corrupt hash in the database is a failed
login, not a 500.

### The template refuses to ship its own secrets

`deployment_warnings()` checks for the shipped JWT secret, a secret shorter than
32 bytes, a well-known seed password, and cookies without the `Secure` flag.

In development these are logged as warnings. When `APP_ENV=production` the
application **refuses to start**. A warning in a log is easy to miss, and a
template that boots happily with its own published JWT secret is exactly how
that secret ends up on the internet.

### The seed

Runs on every container start and is idempotent — it checks for the username
before inserting. It logs a warning when the password is still a known default.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `JWT_SECRET` | a placeholder | Signing key. `openssl rand -hex 32`. Refuses to start in production |
| `JWT_EXPIRE_MINUTES` | `10080` (7 days) | Session lifetime |
| `AUTH_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `SEED_ADMIN_USERNAME` | `admin` | |
| `SEED_ADMIN_PASSWORD` | `admin` | **Change before deploying.** Warned about at startup and in the README |
| `SEED_ADMIN_EMAIL` | `admin@test.com` | |

## Endpoints

| method | path | purpose |
|---|---|---|
| `POST` | `/api/auth/signup` | Create an account and sign in. 201 |
| `POST` | `/api/auth/signin` | Username or email, plus password |
| `POST` | `/api/auth/signout` | Clear the cookie. 204 |
| `GET` | `/api/auth/me` | Current user, or 401 |
| `PATCH` | `/api/auth/me` | Display name and email |
| `POST` | `/api/auth/me/password` | Change password; re-issues the session |

Changing a password re-issues the cookie. Otherwise the act of securing your
account silently signs you out, which reads as a bug.

## How to extend it

- **OAuth / SSO**: add a route that verifies the provider's token, finds or
  creates the user, and calls `_set_session_cookie`. Nothing downstream changes,
  because everything downstream depends on `current_user`, not on how the
  session was established.
- **Roles beyond `is_admin`**: add a table and a `require_role` dependency
  alongside `current_user`.
- **Refresh tokens**: `create_access_token` is one function. Issue a second
  longer-lived token and add a refresh endpoint.
- **Rate limiting**: sign-in is the endpoint that wants it. See known limits.

## Known limits

- **No rate limiting on sign-in.** Brute-forcing is throttled only by bcrypt's
  cost factor. Anything internet-facing wants a limiter in front — nginx
  `limit_req` on `/api/auth/` is the smallest version of this.
- **No email verification and no password reset.** Both need an email provider,
  which is a dependency the template should not pick for you.
- **No refresh tokens.** A session simply expires after `JWT_EXPIRE_MINUTES`.
- **Tokens cannot be revoked before expiry.** Signing out clears the cookie, but
  a copied token stays valid until it expires. Revocation needs server-side
  session state, which is a deliberate omission at this size.
- **`is_admin` is seeded, never granted through the UI.** Promote a user with
  SQL (`make shell-db`).

## Tests

`backend/tests/test_auth_service.py` — 41 tests: salting, verification against a
corrupt hash, the 72-byte limit, token round-trip, expired and malformed tokens,
username and email normalisation, duplicate handling, indistinguishable sign-in
failures, disabled accounts, profile updates including the "keeping your own
email is not a conflict" case, and password changes.

`backend/tests/test_auth_api.py` — cookie flags (`HttpOnly`, `SameSite=lax`), the
token being absent from the response body, bearer-header auth, sign-out clearing
the cookie, 401 and 409 envelopes, session re-issue on password change, and the
deployment-safety checks.

`frontend/src/lib/auth.test.tsx` — session restored from the cookie, a 401
treated as signed out rather than an error, and the loading gate that stops
routes flashing.

## Verified

Signed in through the browser at `http://localhost:8100` as the seeded admin;
session restored on reload; `/api/auth/me` returns the user through the nginx
proxy; unauthenticated access to `/` redirects to `/signin`.
