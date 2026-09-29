# Evidence

How each criterion in the spec beside this file is discharged. States: `open`;
`test: <file>::<test_fn>`; `probe: <file>::<name>`;
`observed: #<PR> <YYYY-MM-DD> <name>`. A criterion whose own text says it is
verified in a browser is dischargeable by `test:` only where the test drives a
real browser over the real launch path — the end-to-end suite (`make e2e-grillui`)
qualifies; a unit test that never renders the page proves something else, and a
hand probe stays `probe:`.

- TRV-A1 | open
- TRV-A2 | open
- TRV-A3 | open
- TRV-A4 | open
- TRV-A5 | open
- TRV-A6 | open
- TRV-A7 | open
- TRV-A8 | open
