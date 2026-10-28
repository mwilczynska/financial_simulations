# Decision records

Decision records preserve why Financial Simulations makes a material modelling or engineering choice. They complement the [detailed methodology](../methodology/README.md), which specifies how the calculations work.

## Register

| Record | Date | Status | Decision |
| --- | --- | --- | --- |
| [0001](0001-daily-returns-throughout.md) | 2026-10-28 | Accepted requirement; implementation pending | Retain daily returns and daily account evolution throughout |
| [0002](0002-methodology-and-decision-records.md) | 2026-10-28 | Accepted documentation workflow | Maintain detailed methodology and referenced reasons with the code |

## When to write a record

Record choices that materially affect interpretation, accounting, data selection, model structure, calibration, calendar handling, sampling, Australian rules or reproducibility. Routine edits do not need their own record.

Each record should identify the context and constraints, alternatives, the decision, why it was made, consequences, references and implementation/validation status. Distinguish a user requirement from a research finding or engineering judgement.

Use the next available numeric identifier and a concise filename. The [template](template.md) supplies a starting structure. Link records from the relevant method documents and vice versa.

If a decision changes, create a superseding record and link both records. Preserve the old reasoning and the status change. An accepted design is not a claim that it has been implemented or validated.
