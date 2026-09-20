# Domain docs

This repo uses one domain context. Its glossary belongs in root `CONTEXT.md`; architecture decisions belong in `docs/adr/`.

## Before exploring

Read `CONTEXT.md` if it exists. Read ADRs in `docs/adr/` that relate to the area you will work on. If those files do not exist yet, continue without them. The `/domain-modeling` skill creates them when terms or decisions are resolved.

## Use the glossary's vocabulary

When naming a domain concept in an issue, proposal, hypothesis, or test, use the term defined in `CONTEXT.md`. If the concept is absent, reconsider the name or note the gap for `/domain-modeling`.

## Flag ADR conflicts

If a proposed change conflicts with an existing ADR, identify that decision and explain why it should be reconsidered.
