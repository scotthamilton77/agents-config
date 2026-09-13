You are the lead of a reproduction run. Do exactly this and nothing else.

1. Call the Agent tool with no name, subagent_type "general-purpose", model "haiku", and this prompt verbatim (everything between the --- lines):
---
You are a subagent. Do exactly this and nothing else, and do not stop early when a tool fails.
1. Call Write with file_path "{RUN_DIR}/solo/report.md" and content "probe".
2. Call Write with file_path "{RUN_DIR}/solo/summary.md" and content "probe".
3. Call Write with file_path "{RUN_DIR}/solo/notes-report.md" and content "probe".
4. Call Write with file_path "{RUN_DIR}/solo/report.txt" and content "probe".
5. Call Bash with command: printf 'seed\n' > {RUN_DIR}/solo/edit-target-report.md
6. Call Edit on file_path "{RUN_DIR}/solo/edit-target-report.md" replacing "seed" with "edited".
7. Call SendMessage with to "main" and message "FINAL REPORT: unnamed subagent. <one line per step, each giving the file name and then either ALLOWED or the exact error text the tool returned>".
8. End with that same list as your final text.
---
2. Call the Agent tool with name "beta", model "haiku", subagent_type "general-purpose", and this prompt verbatim (everything between the === lines):
===
You are a named teammate called beta. Do exactly this and nothing else, and do not stop early when a tool fails.
1. Call Write with file_path "{RUN_DIR}/beta/report.md" and content "probe".
2. Call Write with file_path "{RUN_DIR}/beta/summary.md" and content "probe".
3. Call Write with file_path "{RUN_DIR}/beta/notes-report.md" and content "probe".
4. Call Write with file_path "{RUN_DIR}/beta/report.txt" and content "probe".
5. Call Bash with command: printf 'seed\n' > {RUN_DIR}/beta/edit-target-report.md
6. Call Edit on file_path "{RUN_DIR}/beta/edit-target-report.md" replacing "seed" with "edited".
7. Call SendMessage with to "main" and message "FINAL REPORT: teammate beta. <one line per step, each giving the file name and then either ALLOWED or the exact error text the tool returned>".
8. End your turn.
===
Each agent writes into its own directory, so the two never touch the same file.

3. Each time a message arrives, append one line "<sender> | <text>" to {RUN_DIR}/lead.md using the Write tool (rewrite the whole file with all lines so far). Do nothing else on those turns.
4. When a message beginning "FINAL REPORT" has arrived from both agents, or after you have appended four lines, write the final file and reply with the single word DONE.
