# Issue tracker: Local Markdown

Issues and specs for this repo live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`.
- The spec is `.scratch/<feature-slug>/spec.md`.
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- Triage state is a `Status:` line near the top of each issue file. Use the values in `docs/agents/triage-labels.md`.
- Append conversation history under a `## Comments` heading.

## When a skill says "publish to the issue tracker"

Create a file under `.scratch/<feature-slug>/`, creating the directory if needed.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally provide the path or issue number.

## Wayfinding operations

The map is a file with one child file per ticket.

- Map: `.scratch/<effort>/map.md`, containing Notes, Decisions-so-far, and Fog.
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`. Record its type (`research`, `prototype`, `grilling`, or `task`) in a `Type:` line.
- Blocking: record `Blocked by: NN, NN` near the top. A ticket is unblocked when every listed ticket is resolved.
- Frontier: scan `.scratch/<effort>/issues/` for open, unblocked, unclaimed tickets; the first by number wins.
- Claim: set `Status: claimed` and save before starting work.
- Resolve: append the answer under `## Answer`, set `Status: resolved`, and append a context pointer with a summary and link to Decisions-so-far in `map.md`.
