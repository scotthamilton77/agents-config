# Android app: replacing the image loader

## Problem

On Android devices with 3 GB of memory or less, the app crashes when a feed of large photos scrolls quickly. The crash reporter attributes about a third of all Android crashes to out-of-memory errors in the image loader. The Android crash-free session rate is 99.2 percent.

## What changes

- The app decodes each image downsampled to the size it is shown at, so a large photo no longer loads at full resolution.
- After the change reaches every Android user, the Android crash-free session rate is at least 99.6 percent.

## Decisions

- **D1 Release.** The new loader ships in release 8.4, rolled out to 10, then 50, then 100 percent of Android users over one week.
- **D2 Measurement.** The crash-free session rate is the crash reporter's figure for Android sessions on release 8.4 or later, taken from its daily export.
- **D3 Window.** The window is the 14 days starting the day release 8.4 reaches 100 percent of Android users.
- **D4 Missing data.** A day whose export is missing is fetched from the crash reporter's API. If the API cannot supply it, the window extends by one day for each missing day.

## Acceptance criteria

IMG-A1 and IMG-A2 are automated tests run in CI on the pull request's head on a 2 GB Android emulator, and the pull request does not merge until they pass. IMG-A3 is a live observation. The mobile lead records the rate, the days it covers and the export files read on the rollout item, which stays open until IMG-A3 is decided.

- **IMG-A1** Given a 48-megapixel photo shown in a view 720 pixels square, when the feed displays it, the decoded bitmap is at most 720 by 720 pixels.
- **IMG-A2** Given a feed of 200 48-megapixel photos, when the test scrolls it from top to bottom in 20 seconds, the app process is still running at the end.
- **IMG-A3** Given the window of D3, the crash-free session rate over all of its days, computed from D2's daily exports as crash-free sessions divided by all sessions, is at least 99.6 percent.
  IMG-A3 stays pending until every day of the window has been collected. A rate over part of the window decides nothing.

## Out of scope

- iOS.
- Images in chat messages, which use a different loader.
