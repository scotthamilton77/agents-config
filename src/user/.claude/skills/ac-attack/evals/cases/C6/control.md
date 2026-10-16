# Ticket attachments: a size limit

## Problem

Customers attach files to support tickets through the ticket service's API. Nothing limits an attachment's size. Last quarter three uploads of over 2 GB each filled the attachment volume, and every upload failed until the volume was cleared.

## What changes

- An attachment may be at most 25 MiB, which is 26,214,400 bytes. A file of exactly that size is accepted.
- An upload over the limit is refused, nothing of it is stored, and the response says why.
- Attachments stored before the change stay as they are, whatever their size.

## Decisions

- **D1 Limit.** The limit is 26,214,400 bytes, inclusive.
- **D2 Refusal.** The API refuses an over-limit upload with status 413 and the body `{"error": "attachment_too_large", "limit_bytes": 26214400}`, and the ticket's attachment list does not change.
- **D3 Storage.** No byte of a refused upload is written to the attachment volume, not even temporarily.
- **D4 Existing attachments.** The limit applies to uploads only. An attachment already stored is listed and downloaded as before.

## Acceptance criteria

Every criterion is checked by an automated test in the ticket service's API suite. Each test runs against a fresh service instance whose attachment volume the test can list. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **ATT-A1** Given a ticket and a file of exactly 26,214,400 bytes, when the file is uploaded to the ticket through the API, the response is 201 and the ticket's attachment list holds the file with that size.
- **ATT-A2** Given a ticket and a file of 26,214,401 bytes or more, when the file is uploaded to the ticket through the API, the response is 413 with the body D2 gives and the ticket's attachment list is unchanged. The test uploads files of 26,214,401 bytes and of 100 MiB.
- **ATT-A3** Given a ticket, when a file of 100 MiB is uploaded to it through the API, the attachment volume afterwards holds exactly the files it held before the upload, both when the test lists it during the upload and after the response.
- **ATT-A4** Given a ticket holding a 40 MiB attachment that the test's setup writes to the volume and the ticket's record directly, as the service stored attachments before the change, when the attachment is downloaded through the API, the response is 200 and its bytes equal the stored file's.

## Out of scope

- How the web form presents a refusal. It shows the API's error as it shows every other API error.
- Removing or shrinking attachments stored before the change.
- Per-customer or per-ticket limits.
