# Checkout: paying with a saved card

## Problem

Returning customers retype their card number at every checkout. Most of the orders abandoned at checkout are abandoned at the payment step.

## Outcome

A returning customer who saved a card at an earlier checkout pays with it at the next checkout by entering only its security code (CVC). The work is delivered in three slices, each its own child item:

- **S1 Vault.** The card vault stores a card against a customer and returns a token. Card numbers never leave the vault.
- **S2 Save at checkout.** The payment step offers "Save this card". A payment with the box ticked stores the card through the vault.
- **S3 Pay with a saved card.** The payment step lists the customer's saved cards and charges a chosen one through its token and a CVC entered for that payment.

## Decisions

- **D1 One store.** The vault is the only store of card numbers. Checkout holds only tokens.
- **D2 Display.** A saved card is shown as its brand and last four digits.
- **D3 CVC every time.** Paying with a saved card asks for its CVC every time. The CVC is sent with that charge.

## Acceptance criteria

- **CHK-A1** Given a customer who paid an order with a new card and ticked "Save this card", when they reach the payment step of their next order, the page lists that card by brand and last four digits, and choosing it and entering its CVC completes the order with the payment provider's sandbox recording a charge against that card's token.
- **CHK-A2** Given a card number sent to the vault's store endpoint for a customer, the response holds a token and no more of the number than its last four digits, and a lookup of that token returns the card's brand and last four digits.
- **CHK-A3** Given a payment with "Save this card" ticked, when the same customer next reaches the payment step, the page lists that card by brand and last four digits. Given the box left unticked, the page lists no saved card.
- **CHK-A4** Given a customer whose payment step lists a saved card, when they choose it and enter its CVC, the order completes and the sandbox records a charge against that card's token.
- **CHK-A5** Given a customer who chooses a saved card and leaves the CVC empty, when they submit payment, the page shows `Enter the card's security code`, the order stays open, and the sandbox records no charge.

## Verification

CHK-A2 belongs to S1, CHK-A3 to S2, and CHK-A4 and CHK-A5 to S3. Each is checked by an automated test in its slice's suite against the payment provider's sandbox; a criterion passes when its test passes in CI on the slice's pull request, the CI result decides, and the slice does not merge until its criteria pass. CHK-A1 spans all three slices, and a fourth child, S4 Verification, owns it. Once S1 to S3 have merged, S4 runs the existing tests for CHK-A3 and then CHK-A4 on the main branch against one sandbox customer, so the card CHK-A3's test saves is the card CHK-A4's test pays with; together their observations are CHK-A1's. S4 adds no test of its own. It records both results with the commit they ran on and stays open until both pass there, and the parent item closes only when S4 has closed.

## Out of scope

- Deleting or editing a saved card.
- Saving a card outside checkout.
