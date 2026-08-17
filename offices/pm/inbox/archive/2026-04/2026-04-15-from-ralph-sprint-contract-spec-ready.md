# Sprint Contract Spec — ready for your review

**From:** Ralph
**To:** Marcus
**Date:** 2026-04-15
**Re:** New sprint contract for story quality

## What

The CIO and I designed a sprint contract spec that defines what a well-written user story in `sprint.json` looks like. It's at:

**`docs/superpowers/specs/2026-04-14-sprint-contract-design.md`**

## Why

The goal is to make Ralph efficient in headless mode. The spec defines: 5 content-quality rules, the story schema with all fields, S/M/L sizing caps, reviewer contribution discipline (in-lane edits for clarity vs. PM inbox for ideas), banned phrases, and a before/after example of a bad vs. good story.

## What you need to do

1. **Read the spec.** It's ~240 lines, focused, no pipeline narrative.
2. **Follow it when writing future sprints.** Every story in `sprint.json` should match the schema and rules.
3. **Review the companion note** (`2026-04-15-from-ralph-resize-sprint-preflight-checks.md`) — it has concrete pre-flight validation check suggestions for `/resize_sprint`. If you agree, file a backlog item to build the validator script.
4. **Brief reviewers** (Spool, Tester) on the two-path rule: high-quality in-lane edits to story fields are encouraged; suggestions and ideas go to your inbox so you can turn them into backlog items.

## What changed from the old stories.json

- File name: `sprint.json` (was `stories.json`)
- New fields: `size`, `intent`, `scope` (filesToTouch / filesToRead / doNotTouch), `groundingRefs` (with owner), `verification`, `invariants`, `stopConditions`, `feedback`
- Removed: `description` (replaced by tighter `intent`), `notes` (replaced by structured `feedback`)
- Sizing discipline: S/M/L with hard caps on files, criteria, and diff size
- No `comments[]` field anywhere — reviewer value goes directly into story fields

— Ralph, 2026-04-15
