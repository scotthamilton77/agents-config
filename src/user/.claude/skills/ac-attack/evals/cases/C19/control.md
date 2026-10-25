# Dependency audit in CI

## Problem

Services pin their dependencies in `deps.lock`. Nobody is told when a pinned version gets a published security advisory, and teams find out from incident reports weeks later.

The purpose of this change is a command that CI can use to block a pull request on its dependencies' advisories: the command passes only after it has checked every pinned package and found no high or critical advisory.

## What changes

- A new command, `deps audit`, reads `deps.lock` in the current directory. It asks the advisory service about every pinned package and prints the advisories it gets back.
- The command exits 0 to pass and any other status to fail, which is the convention CI's required checks read.

## Decisions

- **D1 Severity.** An advisory has one of four severities: low, medium, high or critical. The command exits 1 when at least one pinned package has a high or critical advisory, and 0 when none does.
- **D2 Output.** The command prints one line per advisory to stdout, in the form `<package>@<version> <severity> <advisory-id>`, sorted by package name and then by advisory ID, both compared as text, so `ADV-17` comes before `ADV-9`. When there is no advisory, it prints `no advisories`.
- **D3 Advisory service.** The command sends every pinned package in one request to the service's batch endpoint at `https://advisories.internal/batch`, and waits at most 30 seconds for the answer. The endpoint accepts any number of packages in one request. Its answer is a list of advisories, each naming a pinned package, a severity from D1 and an advisory ID. A package the answer does not name has no advisory.
- **D4 Read only.** The command writes no file, keeps no cache, and sends the service nothing but the query. Its output depends only on `deps.lock` and the service's answer.

## Acceptance criteria

Every criterion is checked by an automated test in the command's integration suite. Each test runs `deps audit` in a temporary directory, with the service's address routed to a stub whose answers the test scripts, and asserts on stdout, stderr, the exit status and the requests the stub received. A criterion that lists several cases has a test for each case it lists. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **AUD-A1** Given a `deps.lock` pinning `left-pad@1.0.0` and the stub answering one high advisory `ADV-17` for it, when `deps audit` runs, stdout is `left-pad@1.0.0 high ADV-17` and the command exits 1.
- **AUD-A2** Given a `deps.lock` pinning three packages and the stub answering one medium advisory for the first, one low advisory for the second and nothing for the third, when `deps audit` runs, stdout is exactly the two advisory lines and the command exits 0.
- **AUD-A3** Given a `deps.lock` pinning `zlib@1.3.0` and `acorn@8.0.0`, and the stub answering critical advisories `ADV-9` and `ADV-17` for `zlib` and a low advisory `ADV-2` for `acorn`, when `deps audit` runs, stdout is the `acorn` line for `ADV-2`, then the `zlib` line for `ADV-17`, then the `zlib` line for `ADV-9`, and the command exits 1, because one failing advisory fails the audit whatever else it finds.
- **AUD-A4** Given a `deps.lock` pinning three packages and the stub answering no advisory, when `deps audit` runs, the stub receives one request naming all three packages, stdout is `no advisories` and the command exits 0.
- An audit that finds a high or critical advisory fails the check, which AUD-A1 and AUD-A3 test. An audit that cannot run is covered by AUD-A6 and AUD-A7.
- **AUD-A5** Given a `deps.lock` that parses and pins no package, when `deps audit` runs, the stub receives no request, stdout is `no advisories` and the command exits 0.
- The severity boundary is tested by AUD-A1, which fails on high, the lowest failing severity, and by AUD-A2, which passes on medium, the highest passing one. A package with several advisories is AUD-A3. The number of pinned packages has no limit the command depends on, because D3's endpoint takes any number in one request.
- **AUD-A6** Given no `deps.lock` in the directory, or a `deps.lock` that cannot be read, is empty, holds only whitespace, does not parse, or pins one package more than once, when `deps audit` runs, the stub receives no request, stdout is empty, stderr holds `cannot read deps.lock` and the command exits 2.
- **AUD-A7** Given the stub refusing connections, answering with any status other than 200, answering with a body that is not the advisory list D3 describes, such as one holding a severity outside D1's four, an advisory for a package `deps.lock` does not pin, or the same advisory twice, or not answering within 30 seconds, when `deps audit` runs, stdout is empty, stderr holds `advisory service unavailable` and the command exits 3.
- The command only reads (D4), so neither a repeated run nor two runs at once can change what another run reads or prints.
- A run changes nothing, so a second run with nothing changed has nothing to change beyond the first.

## Out of scope

- Adding `deps audit` to CI as a required check. The CI owners do that once the command exists.
- Upgrading or patching a vulnerable package. The command reports advisories, and people act on them.
- Any change to the advisory service, including how fast it publishes a new advisory.
- Advisories at low or medium severity blocking a merge.
- Checking `deps.lock` against the manifest it was generated from. The package manager owns that check.
