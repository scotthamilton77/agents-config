# Team wiki: archiving stale pages

## Problem

The team wiki's search returns pages nobody has edited in years, and readers follow instructions that stopped being true long ago. Nothing today tells a reader that a page is stale.

## What changes

- An archiving run archives every stale page.
- An archived page drops out of search and stays readable at its URL under a banner.
- An editor restores an archived page with its Restore button.

## Decisions

- **D1 Stale.** A page is stale when its last edit is more than 365 days before the archiving run. Viewing a page is not an edit, so a page viewed recently but not edited is still stale.
- **D2 Archived.** An archived page appears in no search result, whether the query matches its title or its content, and its URL returns HTTP 200 with the banner "This page is archived and may be out of date." above its content. A page that is not archived appears in search for its title and its content, and its URL shows no banner.
- **D3 Restore.** Pressing Restore on an archived page makes it not archived, and the restore counts as an edit of the page at that moment for D1.
- **D4 Preservation.** Archiving a page leaves its URL, its content and its revision list unchanged, and a later archiving run over a page already archived leaves its content and its revision list unchanged.

## Acceptance criteria

Every criterion is checked by an automated test in the wiki's end-to-end suite. The suite runs against a seeded database with a controllable clock, which stands still while an archiving run runs, so a run has one time. "Archived as D2 defines it" is checked by a search for the page's title, a search for a phrase from its content, and an open of its URL. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **WIK-A1** Given a wiki of seven pages last edited 0 days, 1 day, 364 days, exactly 365 days, 365 days and one second, 366 days and 1,000 days before the run, the 366-day page having been viewed the day before the run, when the archiving run runs, the last three pages are archived as D2 defines it and the first four are not archived as D2 defines it, and a second archiving run immediately afterwards leaves the same seven outcomes.
- **WIK-A2** Given two pages last edited 366 days before the run, one with a single revision and one with five, when the archiving run archives them, each page's URL is unchanged, and its content and revision list read through the page API are byte-identical to what they were before the run, and they are still byte-identical after a second archiving run immediately afterwards.
- **WIK-A3** Given a page archived by a run, when an editor presses its Restore button, the page is not archived as D2 defines it, it is still not archived as D2 defines it after an archiving run exactly 365 days after the restore, and it is archived as D2 defines it after an archiving run 365 days and one second after the restore.
- **WIK-A4** Given an archived page, when a reader opens its URL, the page shows, below the banner, links to the three most-viewed pages in the same space that are not archived.

## Out of scope

- Deleting archived pages.
- Notifying a page's owner before or after the page is archived.
- Scheduling the archiving run. Operations schedules it with the existing job scheduler.
