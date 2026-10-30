# ADR 0032: start a too-early pension when super becomes accessible

Date: 2026-10-30. Status: accepted; implemented and locally validated.

## Context

The planner's `pension.start_age` (default 60) and `person.retirement_age`
are separate inputs. The ledger rejects a pension that commences before the
person's unrestricted access date with `UnsupportedRule`, because before
then the only available income stream is a transition-to-retirement pension,
which is not modelled ([ADR 0014](0014-single-person-ledger-conventions.md)).
Access comes at retirement after preservation age, or at 65
(`access_date` in `rules/au/superannuation.py`).

A user set retirement age 65 with the pension at 60. The pension would have
started five years before retirement, every retirement path hit the rule, and
the plan could not run at all. Any pension age between preservation age and
a later retirement age below 65, or before 65 with retirement at 65 or later,
had the same result.

## Alternatives considered

1. Keep rejecting the plan. It is accurate but unhelpful: the message names
   a rule the user did not ask for, and the input form allows the combination.
2. Reject the combination during plan validation with a field message. It is
   clearer, but still stops the run for an intent that has an obvious reading.
3. Model transition-to-retirement pensions. This is the most faithful, but it
   needs the 4–10% drawdown band, taxed earnings on TTR assets, and the
   conversion to a retirement phase pension at a release condition. It is a
   larger piece of work.
4. Start the pension on the later of the requested age and the access date,
   and report the change.

## Decision

Alternative 4. `build_inputs` in `retirement/plan.py` commences the pension
on `max(plan start, birthday(start_age), access_date)`, using the same access
rule as the ledger. When the requested date is earlier, it adds a run note
naming the access date and that transition to retirement is not modelled.
The ledger's check is unchanged, so a direct ledger scenario still fails
loudly. The app's withdrawal-strategy summary states the effective date.

## Reasons and evidence

The user asked for the plan to run with these inputs (user requirement).
Starting the pension at access matches the most likely intent, "move super
into a pension as soon as I may", and is what a retiree in the modelled scope
would do (engineering judgement). Before the access date, spending is
already paid from cash and outside investments, as for any plan with super
not yet accessible.

## Consequences

Plans that previously failed now run, with a visible note. A user who
actually wanted transition to retirement does not get it; the note says so.
Revisit if TTR pensions are modelled (alternative 3).

## Implementation and validation

`build_inputs` and the app summary/help text changed. The test
`test_pension_before_super_access_starts_when_super_becomes_accessible` in
`tests/test_plan.py` checks a 60/65 plan commences at the 65th birthday with
the note, and a 60/60 plan is unchanged. Documented in
[plan-and-app.md](../methodology/plan-and-app.md) and
[retirement-ledger.md](../methodology/retirement-ledger.md).
