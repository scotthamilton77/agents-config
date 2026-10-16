# Budget app: the empty Accounts screen

## Problem

A new user who skips the setup wizard lands on an Accounts screen showing an empty list and nothing else. Support receives several emails a week from such users asking how to add an account, and many of them never return to the app.

## What changes

- An Accounts screen with no active account shows an empty state: a heading, a short explanation and two buttons, Link a bank and Add a cash account.
- Link a bank opens the existing bank-linking flow. Add a cash account opens the existing cash-account form.
- Once the user has an active account, the screen shows the account list as it does today.

## Decisions

- **D1 Layout.** The empty state is a heading, body text of at most two sentences, and the two buttons, in that order. The content designer writes the copy.
- **D2 Actions.** Link a bank is the primary button and Add a cash account the secondary button.
- **D3 When it shows.** The empty state shows only when the user has no active account. An archived account does not count as active.
- **D4 Evaluator.** The design lead is the evaluator for the empty state, as ACC-A6 states.

## Acceptance criteria

Each criterion names its check. An automated check is a UI test in the app's instrumented suite, run in CI on the pull request's head on a phone emulator and a tablet emulator. It passes when the test passes on both. A human check is recorded as a comment on the pull request giving the evaluator's verdict, the reason for it and the build judged. The pull request does not merge until every criterion passes.

- **ACC-A1** Given a signed-in user with no account, when the Accounts screen opens, it shows the heading, the body text and the two buttons D2 names, and no account list. Checked by a UI test.
- **ACC-A2** Given the empty state, when the user taps Link a bank, the first screen of the bank-linking flow opens. Checked by a UI test.
- **ACC-A3** Given the empty state, when the user taps Add a cash account, the cash-account form opens. Checked by a UI test.
- **ACC-A4** Given a user whose only account is archived, when the Accounts screen opens, it shows the empty state. Checked by a UI test.
- **ACC-A5** Given a user with one active account, when the Accounts screen opens, it shows that account in the list and no empty state. Checked by a UI test.
- **ACC-A6** Given the empty state on the release-candidate build, the design lead reviews it. It passes when the design lead approves it.

## Out of scope

- Changes to the bank-linking flow or the cash-account form.
- Empty states on any other screen.
