# Merge Guard Comment Counting

`merge-guard` counts all inline PR review comments including your own reply comments. If it false-blocks with `unseen_comments` after triaging all reviewer threads, verify the extras are your own replies, then re-run with `--comments-seen` equal to the total comment count (reviewer comments + your replies).
