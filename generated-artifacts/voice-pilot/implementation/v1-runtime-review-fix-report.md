# Native runtime review dependency fix

## Scope

This isolated fix addresses only the independent Task 3 runtime review findings:

- Confirmation now compares the latest caller utterance with the model-selected
  response exactly after case folding, whitespace normalization, and removal of
  trailing sentence punctuation. A missing latest utterance rejects. The
  previous substring matcher remains unchanged for non-consent collection
  behavior. The existing explicit `no` and `edit` routes remain supported.
- Initial-node `systemPrompt` is carried as private guidance once; a duplicate
  developer message was removed.

No host/editor, ledger, provider, or action-broker files are part of this fix.

## Evidence

- Red: guarded `test_native_graph_runtime.py` run failed on the actual pipeline
  case where caller utterance `yes, but I need to change the room` was accepted
  as confirmation, and on the duplicate initial system prompt assertion.
- Green: `flock /tmp/botelier-flow-v1-guard.lock env -i ... lifecycle_guard.py
  --tests .../test_native_graph_runtime.py` — **20 passed**, **0 guard-blocked
  attempts**. The suite includes actual pipeline qualified/negative consent
  cases, a valid simple `yes`, and the existing allowed `edit` flow.
- `git diff --check` passed before commit.

## Limitation

The affirmative contract is deliberately strict: the latest caller utterance
must match the action response (`yes`, `no`, or `edit`) exactly after the limited
normalization above. Longer affirmative phrases such as “yes, please” are
rejected until an explicit reviewed phrase allowlist is designed. This is a
fail-closed consent choice.
