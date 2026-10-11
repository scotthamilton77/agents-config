# Self-service password reset

## Problem

A user who forgets their password has to email support and wait for a manual reset. That takes a day on average, and these emails are a fifth of support's volume.

## What changes

- A user requests a reset from the sign-in page and receives an email with a link.
- Following the link within 30 minutes, the user sets a new password and signs in with it. The old password stops working.

## Decisions

- **D1 Token.** A reset token is single use and expires 30 minutes after it is issued. Issuing a new token for an account invalidates the account's earlier tokens.
- **D2 No disclosure.** The request page shows the same message whether or not the address belongs to an account.
- **D3 Password rule.** A new password has at least 12 characters, the rule sign-up already applies.
- **D4 Slices.** S1 builds token issue and validation, S2 the reset email, and S3 the reset page. S4 is the verification child of PWR-A1: an end-to-end test that drives a browser through the reset on the staging environment and reads the email from staging's mail sink.

## Acceptance criteria

Each slice's criteria are checked by automated tests run in CI on that slice's pull request head, and the pull request does not merge until they pass. S4's end-to-end test runs against staging after a deploy.

- **PWR-A1** Given a user with an account, when they request a reset, follow the emailed link within 30 minutes and set a new password, then signing in with the new password succeeds and signing in with the old one is refused. This outcome spans S1 to S3.
  S4 closes PWR-A1. S4 stays open until its end-to-end test passes against a staging deploy carrying S1, S2 and S3. Closing S1, S2 and S3 closes neither S4 nor PWR-A1.
- **PWR-A2** (S1) Given a token issued 31 minutes ago, the validation endpoint refuses it with status 410.
- **PWR-A3** (S1) Given a token already used once, the validation endpoint refuses it with status 410.
- **PWR-A4** (S1) Given an account with an unused token, when a second token is issued for it, the validation endpoint refuses the first with status 410.
- **PWR-A5** (S2) Given a reset request for an address with an account, the mail sink holds one email to that address within 60 seconds, whose link carries a token the validation endpoint accepts.
- **PWR-A6** (S2) Given a reset request for an address with no account, the request page shows the message it shows for an address with an account.
- **PWR-A7** (S3) Given a valid token, when the user submits an 11-character password on the reset page, the page refuses it with the message sign-up shows for a short password.

## Out of scope

- Resetting a password by text message.
- Changing a password while signed in.
