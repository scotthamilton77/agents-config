# Decision: how the storefront evaluates feature flags

## Problem

The storefront turns features on and off through environment variables, so every change to a flag needs a deploy. Product teams want to release a feature to a share of customers, widen it over days, and switch it off within a minute when it misbehaves. This item decides how flags will work. It builds nothing.

## Options

- **O1** Build flag evaluation into the existing configuration service.
- **O2** Use a hosted feature-flag vendor.
- **O3** Run an open-source flag server on our own infrastructure.

## Constraints

- **K1** A flag check in the request path makes no network call. Flags are evaluated in-process from a local copy.
- **K2** Customer identifiers used for targeting stay in EU data centres.
- **K3** The total cost is under 40,000 euros a year at today's traffic, counting the engineering time to build or run it.
- **K4** A flag can target a percentage of customers and a named customer segment.
- **K5** A change to a flag reaches every storefront instance within 60 seconds.

## Decisions

- **D1 Deliverable.** The item delivers a decision record that chooses one option.
- **D2 No option fits.** When no option meets every constraint, the record still chooses one. It names each constraint the choice breaks and carries the engineering manager's written acceptance of each break.
- **D3 Evidence.** A verdict on a constraint counts as supported when it cites vendor documentation, a published price, or a measurement from a prototype built for this decision.

## Acceptance criteria

The criterion below is a human check. The architecture group records its verdict in the minutes of its weekly review, naming the revision of the record judged. The item closes only on a recorded pass.

- **FLG-A1** The decision record names one chosen option and states, for each of O1 to O3, whether it meets each of K1 to K5, with every verdict supported as D3 requires. The architecture group, which agreed these points with the engineering manager before the work started, judges the record against them and against D2. It passes when the group records every point as met, naming any point that fails.

## Out of scope

- Implementing the chosen option.
- Migrating the existing environment-variable flags.
