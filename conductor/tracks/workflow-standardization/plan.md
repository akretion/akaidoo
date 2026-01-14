# Track: Workflow & State Management

## Context
Moving away from ad-hoc usage towards a structured "Session" based workflow compatible with Agents.
Take inspiration from Byterover.

## Goals
1. Establish `.akaidoo/` as the state directory.
2. Implement `init` command.

## Tasks

- [x] **Command: `akaidoo init`**
    - [x] Create `.akaidoo/` directory in CWD.
    - [x] Create `.akaidoo/rules/oca_guidelines.md` (Pre-seed with default rules).

- [x] **Session Context**
    - [x] When running `akaidoo addon -o`, output to `.akaidoo/context/current.md` by default if no path is given.
    - [x] Update `.akaidoo/context/summary.json` with the list of addons currently in the context.