# ADR 0002: maintain methodology and reasons with the code

Date: 2026-10-28.

Status: accepted documentation workflow.

## Context

The project will combine empirical financial data, stochastic models and Australian tax/super rules. Results depend on assumptions and choices that can otherwise become hidden in code or lost between working sessions.

The user requested detailed methodology documents written over time, including why decisions were made and references where available.

## Alternatives considered

1. Keep implementation notes mainly in code comments and working-session discussions.
2. Write a methodology report after implementation is complete.
3. Maintain versioned method specifications and decision records alongside each coherent implementation checkpoint.

## Decision

Use alternative 3. Maintain a [methodology register and standard](../methodology/README.md) and this decision register. Each material model/calculation gets a detailed method document. Material choices get a dated record of context, alternatives, selection, reasons, consequences and evidence.

Update methods, implementation status and validation evidence with the relevant code change. Commit and push reviewed milestones regularly, as requested by the user. Preserve superseded reasoning through linked records and Git history.

## Reasons and evidence

- **User requirement:** the explanations and reasons are part of the intended deliverable, developed over time.
- **Engineering judgement:** versioned explanations make results easier to reproduce and allow later changes to be assessed against the original assumptions.
- **Evidence discipline:** references must support specific claims. Distinguish user requirements, verified facts, scoped research findings and engineering judgements. The [literature review](../literature-review.md) demonstrates why methodological applicability and access limitations need to be explicit.

This workflow is a project decision; no external paper is claimed to prove that it is the uniquely correct documentation structure.

## Consequences

Implementation milestones include documentation and appropriate validation. Proposed, implemented and validated behaviour need different status labels. References to changeable data or rules need versions/effective dates, and relevant access dates.

Documentation grows with the project; the register is not a claim that every listed method has already been researched or implemented. Private scenarios, reports and personal financial details remain outside committed documents.

## Implementation and validation

The methodology register, daily-engine design, decision register and reusable decision template are present. Repository agent instructions record the workflow. Model-specific documents and actual validation results will be added as their work begins.
