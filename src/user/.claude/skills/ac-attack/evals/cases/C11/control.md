# Contact sync: pacing under the vendor's rate limit

## Problem

A nightly job copies changed contacts from the CRM to the email vendor through the vendor's REST API, one request per contact. On a night with more than 60 changes the vendor answers 429 to most requests after the first minute. The job counts each 429 as a failure, so those contacts stay out of date until someone reruns the job.

## Current state

- The vendor's API reference, on its rate-limits page as retrieved on 2026-09-14, states: "Each API key may make at most 60 requests in any rolling 60-second window. A request beyond that receives 429 with a Retry-After header giving the seconds to wait."
- The job uses one API key, and nothing else uses that key.
- The run log of 2026-09-13 shows 4,212 changed contacts, the first 429 at the job's 61st request, and 3,987 contacts not delivered.

## What changes

- The job paces its requests so that it stays within the vendor's limit for its key.
- A 429 the job still receives is retried after the delay the vendor asks for, and is not counted as a failure unless retries run out.

## Decisions

- **D1 Pacing.** The job spaces its requests so that no rolling 60-second window holds more requests than the vendor's limit for the key. Retried requests count toward the window.
- **D2 Responses.** A 2xx response delivers the contact. On a 429 the job waits the seconds the Retry-After header gives, or 60 seconds when the header is absent. It then sends the same request again as soon as D1's pacing allows, so the wait can be longer than the header asks but never shorter. It retries one contact at most five times. When the fifth retry also receives 429, the job records the contact as failed and moves on. Any other outcome, whether another response status or no response within 30 seconds, records the contact as failed at once, without a retry.
- **D3 Exit status.** The job exits 0 when every changed contact was delivered, and 3 when any contact was recorded as failed. The run log lists the ID of each failed contact.

## Acceptance criteria

Every criterion is checked by an automated test in the job's integration suite. The suite runs the job against a stub of the vendor API that records each request's arrival time and answers as the test scripts it. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **SYN-A1** Given the vendor's limit of 60 requests in any rolling 60-second window and 200 changed contacts, when the job runs against a stub answering 200 to every request, the stub records a request for each of the 200 contacts, and each request arrives more than 60 seconds after the request 60 places before it.
- **SYN-A2** Given a stub that answers a contact's first request with 429 and `Retry-After: 7`, and its second with 200, when the job runs over that one contact, the second request arrives at least 7 seconds after the first and the job exits 0. The test repeats with a 429 that carries no Retry-After header, and expects the second request at least 60 seconds after the first.
- **SYN-A3** Given three changed contacts and a stub that answers every request for the second with 429 and `Retry-After: 1`, and every other request with 200, when the job runs, the stub records six requests for the second contact, the run log lists its ID as failed, the first and third are delivered, and the job exits 3.
- **SYN-A4** Given three changed contacts and a stub that answers every request for the second with 500, and every other request with 200, when the job runs, the stub records one request for the second contact, the run log lists its ID as failed, the first and third are delivered, and the job exits 3. The test repeats with a stub that never answers the second contact's request, and expects the same result.
- **SYN-A5** Given no changed contacts, when the job runs, the stub records no request and the job exits 0.

## Out of scope

- Using more than one API key.
- Runs that do not finish before the next night's run. The largest night in the past year had 9,140 changes, about two and a half hours at the vendor's limit.
- Changes to which contacts count as changed.
