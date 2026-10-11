# Project API: permissions by role

## Problem

Every member of a project can call every action of the project API today. A viewer invited to read a roadmap can also delete it.

## What changes

- The project API decides each of its four actions by the caller's role on the project, as the matrix in D1 gives.
- A refused action leaves the project as it was.

## Decisions

- **D1 Matrix.** The four actions are read, comment, edit and delete. A viewer may read. A commenter may read and comment. An owner may do all four. Every other pairing of role and action is refused. An allowed read returns the project, an allowed comment adds the comment to it, an allowed edit replaces its body with the one sent, and an allowed delete removes it.
- **D2 Refusal.** A refused action returns HTTP 403 with the body `{"error": "forbidden"}`, and the project, as an owner reads it afterwards, is unchanged.
- **D3 No role.** A caller with no role on the project gets, for each of the four actions, the same response a request for a project that does not exist gets, apart from the values of the `Date` and `X-Request-Id` headers, which have the same format as for a project that does not exist. The project is unchanged.

## Acceptance criteria

Every criterion is checked by an automated test in the API's integration suite. Each request in a test is sent to a freshly seeded project P, which holds a title, a body, two comments and a revision list, whose callers are one viewer, one commenter, one owner and one user with no role. A second project Q is seeded beside P, on which the viewer and the user with no role on P are both owners, so a decision taken from the caller's role on another project fails. In PRM-A1 and PRM-A3, each caller first sends a read to Q and then its request to P. "The project as an owner reads it" means the responses of the read action for P's title, body, comments and revision list. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **PRM-A1** Given P, when each of the viewer and the owner sends each of the four actions, the eight responses follow D1. Each allowed action returns 2xx and takes effect: a read returns P's title, body, comments and revision list as seeded, a comment then appears in P's comments after the seeded ones, which remain, an edit changes P's body to the one sent, and a delete makes every caller's next read of P return 404. Each refused action returns HTTP 403 with the body `{"error": "forbidden"}`.
- **PRM-A2** Given P, when each of the six refused pairings of D1 is sent, the project as an owner reads it afterwards is byte-identical to what it was before that request.
- **PRM-A3** Given P, when the user with no role sends each of the four actions, every response's status, body and headers other than `Date` and `X-Request-Id` are identical to those of the same action on a project that does not exist, those two headers have the same format in both, and the project as an owner reads it afterwards is byte-identical to what it was before.

## Out of scope

- Assigning or changing roles. The existing membership screen does that, unchanged, and gives each caller one role per project.
- API actions other than the four D1 names.
