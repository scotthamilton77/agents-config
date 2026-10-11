# Help desk: acknowledgement replies

## Problem

A customer who opens a ticket by email hears nothing until an agent picks the ticket up, which can take a working day. Many customers write again to ask whether the first email arrived, and each such email opens a second ticket for the same request.

## What changes

- The help desk replies to every ticket opened by email within one minute, with an acknowledgement.
- The acknowledgement carries the ticket number and the response time the ticket's priority promises.
- A customer's reply to the acknowledgement joins the same ticket and opens no new one.

## Decisions

- **D1 Response times.** Priority 1 promises 2 business hours, priority 2 promises 8 business hours and priority 3 promises 3 business days. The acknowledgement states the time for the priority the ticket has when it opens.
- **D2 Subject.** The acknowledgement's subject is `[#<ticket-number>] We have your request`.
- **D3 Threading.** An inbound email whose subject carries `[#<ticket-number>]` for an open ticket is added to that ticket as a customer comment.
- **D4 No loops.** An inbound email carrying an `Auto-Submitted` header with any value other than `no` opens its ticket and receives no acknowledgement.
- **D5 Wording.** The support lead owns the acknowledgement's wording. The support lead and the product owner agreed the wording checklist in HDA-A5 before implementation started.

## Acceptance criteria

Each criterion names its check. An automated check is a test in the help desk's integration suite, which runs the mail pipeline against a mail sink that captures every outbound email. It passes when the test passes in CI on the pull request's head. A human check is recorded as a comment on the pull request naming the evaluator, the verdict, each checklist item that failed and the commit judged. The pull request does not merge until every criterion passes.

- **HDA-A1** Given a ticket opened by email from a customer address, when the pipeline processes it, the mail sink holds exactly one email to that address within 60 seconds, with the subject D2 gives. Checked by an automated test.
- **HDA-A2** Given one ticket of each priority opened by email in the staging help desk, the support lead opens each ticket's acknowledgement and confirms that its body holds that ticket's number and the response time D1 gives for its priority. It passes when the support lead records all three acknowledgements as confirmed.
- **HDA-A3** Given an open ticket, when the customer replies to its acknowledgement, the ticket gains one customer comment holding the reply's text and the help desk holds no new ticket. Checked by an automated test.
- **HDA-A4** Given an inbound email carrying `Auto-Submitted: auto-replied`, when the pipeline processes it, the mail sink holds no email to its sender. Checked by an automated test.
- **HDA-A5** Given the acknowledgement rendered for a priority-2 ticket on the pull request's head, the support lead judges its wording against the agreed checklist: a customer who knows nothing of the product can tell that the request arrived and when to expect an answer; the tone is courteous and does not blame the customer; and nothing in it reads as a request for the customer to act. It passes when the support lead records every item as met.

## Out of scope

- Changes to the response times themselves.
- Acknowledgements for tickets opened by chat or by phone.
