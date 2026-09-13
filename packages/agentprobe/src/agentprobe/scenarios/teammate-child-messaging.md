You are the lead of a reproduction run. Do exactly this and nothing else.

1. Call the Agent tool with name "alpha", model "haiku", subagent_type "general-purpose", and this prompt verbatim (everything between the --- lines):
---
You are a named teammate called alpha. Do exactly this and nothing else.
1. Call the Agent tool (no name, subagent_type general-purpose, model haiku) with this prompt verbatim (everything between the ### lines):
###
You are a subagent spawned by a teammate named alpha. Do exactly this and nothing else: call SendMessage with to "team-lead" and message "CHILD-TO-TEAMLEAD"; then call SendMessage with to "main" and message "CHILD-TO-MAIN"; then call SendMessage with to "alpha" and message "CHILD-TO-ALPHA"; then end with the final text "child done".
###
2. The Agent call may return at once with a launch notice instead of a result. Either way, continue immediately: call SendMessage with to "main" and message "UPDATE 1: agent tool returned: <the first line of what the tool returned>".
3. Call SendMessage with to "team-lead" and message "UPDATE 2: via team-lead".
4. Call SendMessage with to "main" and message "FINAL REPORT: alpha done".
5. End your turn.
6. If you are later resumed with a message from anyone, call SendMessage with to "main" and message "RESUMED: <the message you received>", then end your turn again.
---
2. Then wait. Messages will arrive as new turns. Each time one arrives, append one line "<sender> | <text>" to {RUN_DIR}/lead.md using the Write tool (rewrite the whole file with all lines so far). Do nothing else on those turns.
3. When a message beginning "FINAL REPORT" has arrived from alpha and at least one line contains "RESUMED", or after you have appended five lines, write the final lead.md.
4. Then, as your very last act, call Write with file_path "{RUN_DIR}/done" and content "done". Write that file only after the final lead.md, and never before.
