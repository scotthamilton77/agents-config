# The change record's fields

The record is one JSON document. The schema beside this file gives every field's name and type. This table gives what each group holds, who writes it, and which of its fields hold wording an editor may change.

| Group | Holds | Written by | Rewritable |
| --- | --- | --- | --- |
| `pr` | number, title, commit type, component, head commit | the author; the number once the pull request is open | the title's wording |
| `work_item` | the tracker's full id, a gloss, and which slice of its parent item this pull request is | the author | the gloss |
| `summary`, `heads_up` | the opening of the pull request body and its caveats | the author | yes |
| `where_this_fits` | ancestry, the merged pull requests this one builds on, the open ones it runs beside, and the parent item's scope table | generated from the tracker and from GitHub | no |
| `risk`, `blast_radius` | the risk rows, a flag saying whether the change reaches outside its package, two Mermaid sources, and on a spec pull request the items the spec mints | the author | the risk rows' cells |
| `changes`, `design_notes` | the changes by topic, and the reasoning behind them | the author | yes |
| `discovered` | filed, not-filed and in-flight rows | generated from the tracker for filed rows; the author for the rest | the reason of a not-filed or in-flight row |
| `verification` | each gate with its exit status and where it ran, and what was not run | the author | no |
| `campaign` | one row per reviewer, the terminal commit, and every finding | generated from the posted review verdicts | no |
| `criteria` | each criterion's id, its promise in plain words, and its evidence | the author | the promise |
| `commit` | the subject, the three body sections or the reason there are none, and the attribution | the author | the body sections and the subject's wording |
| `replies` | per finding: the claim id, artifact class and finding id that name it, then outcome, change, verification, and the commit | the author | change and verification |
| `record` | schema version, revision, digest, comment id, head commit at publication, and rewrite entries | set when the record is published or its wording is rewritten | no |

## Conventions

- **Emptiness is stated.** `heads_up`, `discovered.rows` and `verification.not_run` hold the single entry `"None."` when there is nothing to say. That entry never sits beside another.
- **A generated part is never typed.** Its content is copied from the tracker or from GitHub. `digest` in `where_this_fits` and in `campaign`, and `filed_digest` in `discovered`, hold the generator's stamp over that content. `lint-rules.md` beside this file says what a stamp covers.
- **A finding is named by three things.** A campaign finding carries its claim id, its artifact class and its finding id, and a reply names its finding by the same three.
- **A generated heads-up row is marked.** It opens with its generator's name and a colon. It is not rewritable.
- **Facts are never reworded.** Ids, URLs, commands, commit ids, counts, statuses, dispositions and attribution are facts. In `pr.title` and `commit.subject` the type, the component and the bracketed id are facts too, and only the wording between them may change.
- **A commit id is forty hex characters** in `pr.head_sha`, `campaign.terminal_sha` and `record.head_sha`. An empty string means the commit is not known.
- **A Mermaid source carries no fence.** The pull request body's template supplies it.
- **A spec's blast radius is the items it mints.** `blast_radius.mints` holds one entry for each tracker item the spec's implementation is cut into. An entry says what the item is in `what`, and gives the item's tracker id in `id` once the item is minted.
- **`criteria` is one line on a spec pull request.** The line says whether the criteria were attacked and where the attack record is. Every other type that carries criteria holds the table.
