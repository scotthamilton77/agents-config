# Accounts: password-reset links expire

## Problem

A password-reset link works forever and works any number of times. A link left in an old email lets anyone who reads that email take over the account.

## What changes

- A reset link stops working 30 minutes after it is sent, and once it has set a new password.
- A link that has stopped working shows a page saying so, with a button that emails a new link.

## Decisions

- **D1 Lifetime.** A link opens the new-password form, and a form opened from it sets a new password, only while less than 30 minutes have passed since the link was sent.
- **D2 Single use.** A link sets a new password at most once, even when two forms opened from it are submitted at the same moment. Once it has, opening it again does not show the form.
- **D3 Expired page.** An expired or used link opens a page showing "This link has expired" and a "Send a new link" button, and no new-password form. Pressing the button emails one new link, carrying a new token, to the account's address.
- **D4 Link shape.** The mobile app opens reset links itself and parses only the shape `https://example.com/reset?token=<token>`. Every reset link the service emails, including one sent from the expired page, has exactly that shape.

## Acceptance criteria

Every criterion is checked by an automated test in the account service's end-to-end suite, which runs with a controllable clock and captures sent email in a test outbox. "The expired page" means the page D3 describes: the message, the button and no new-password form. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **PWR-A1** Given a link sent at 10:00:00, when it is opened at 10:00:00 and at 10:29:59, each opening shows the new-password form, and when it is opened at 10:30:00, it shows the expired page.
- **PWR-A2** Given a link sent at 10:00:00 whose form was opened at 10:29:00, when that form is submitted at 10:30:00, the account's password is unchanged and the response is the expired page.
- **PWR-A3** Given a link sent at 10:00:00 and two forms opened from it at 10:05:00, when the first form sets a new password and the second is then submitted with another, the password is the one the first form set, and opening the link again shows the expired page. In a second run of the same setup, when both forms are submitted at the same moment with different passwords, exactly one submission sets its password and the other receives the expired page.
- **PWR-A4** In two runs, one from the expired page an expired link reaches and one from the expired page a used link reaches, each with a second link sent to the same account earlier and never used: when the user presses "Send a new link", the outbox holds exactly one new email, addressed to the account's address, whose link carries a token different from both earlier links' tokens and opens the new-password form, and the link that reached the page still shows the expired page.
- **PWR-A5** Given a reset request, and separately a press of "Send a new link", the link in each email sent matches `https://example.com/reset?token=` followed by one or more URL-safe characters, with no other path segment or query parameter.

## Out of scope

- Changing the 30-minute lifetime per account or per organisation.
- Rate-limiting how many reset links an account can request.
