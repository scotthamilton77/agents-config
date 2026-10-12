# Reporting API: scoped, expiring tokens

## Problem

The reporting API accepts one shared key per customer. The key never expires and opens every report. When one customer's integration leaked its key, every report that customer holds was exposed.

## What changes

- A customer administrator creates tokens in the admin console. Each token is limited to chosen report types and expires after a chosen number of days.
- The API refuses a token outside its scope, past its expiry, or revoked.
- The service keeps no copy of a token's secret in its storage or its logs.

## Decisions

- **D1 Scope.** A token carries a list of report types. A request for a report type outside that list gets 403 with the body `{"error":"out_of_scope"}`.
- **D2 Expiry.** A token's lifetime is 1 to 365 whole days, and it expires at its creation time plus that lifetime. A request with an expired token gets 401 with the body `{"error":"token_expired"}`.
- **D3 Revocation.** Once a token is revoked in the console, a request with it gets 401 with the body `{"error":"token_revoked"}`.
- **D4 Secrecy.** The service stores only a hash of a token's secret. Neither its storage nor its logs hold the secret as plain text or in any encoding the service uses: base64, hex or URL encoding.

## Acceptance criteria

- **TOK-A1** Given a token scoped to `invoices`, when a client requests `GET /reports/invoices` with it, the response is 200 with the invoices report.
- **TOK-A2** Given a token scoped to `invoices`, when a client requests `GET /reports/payroll` with it, the response is 403 with the body `{"error":"out_of_scope"}`.
- **TOK-A3** Given a token created with a 1-day lifetime and the service clock then advanced by 24 hours and 1 second, when a client requests `GET /reports/invoices` with it, the response is 401 with the body `{"error":"token_expired"}`.
- **TOK-A4** Given a token revoked in the console, when a client next requests `GET /reports/invoices` with it, the response is 401 with the body `{"error":"token_revoked"}`.
- **TOK-A5** Given a token just created, when every table of the token store is dumped, the dump holds the secret neither as plain text nor in base64, hex or URL encoding, and the stored hash verifies against that secret.
- **TOK-A6** Given a token whose secret is used in requests that receive 200, 401 and 403 responses, when the service's log output for that run is collected, it holds the secret neither as plain text nor in base64, hex or URL encoding.
- **TOK-A7** Given an administrator creating a token with a lifetime of 0 or 366 days, when they submit the form, the console shows `Lifetime must be 1 to 365 days` and no token is created.

Criteria TOK-A1 to TOK-A7 are each checked by an automated test in the API's integration suite, which runs the service and the console against a test database. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes. The security team's static-analysis scan also runs on every pull request; its findings are advisory and discharge no criterion.

## Out of scope

- Retiring the old shared keys, which keep working until their own retirement date.
- Rotating a token in place.
