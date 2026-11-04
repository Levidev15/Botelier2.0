# Voice flow pilot: safety checkpoint

## Status

**Preparation is not release approval. Actual image, provider-startup and Azure
results require separate recorded evidence; local imports do not close the gate.**

The CI candidate is published on `candidate/azure-flow-image-checks`, based on
GitHub `main` in `Levidev15/Botelier2.0`. Only pilot preparation and offline fixtures
are included; unrelated unpublished workspace changes are not exported. The
running application, production Dockerfile, backend requirements, production voice
source and existing editor are unchanged.

GitHub workflow-file authorization and candidate publication have been verified.
This does not authorize a merge to `main`, production workflow dispatch, Azure
provisioning, provider calls or any live traffic change.
Prepared workflow safeguards do not protect GitHub until separately reviewed and
applied there; the existing production automation remains unchanged.

The approved implementation sequence is retained in the Replit checkout at
`.local/tasks/azure-voice-flow-pilot.md`. Do not skip from local results to a graph
adapter, pilot activation or a production release.

## What this checkpoint prepares

- A build-only candidate workflow with a read-only repository token, no Azure
  authentication, no production/provider secrets, no registry push and no call
  routing. Its offline containers use `--network none` and a read-only filesystem.
- A separate `Dockerfile.flow-pilot`, not a modification to the production image.
  It uses the exact public Pipecat 1.5.0 wheel artifact plus three explicit,
  hash-checked Flux overlays that reproduce the installed development runtime.
- A source-integrity check against the wheel's `RECORD` and that overlay manifest.
  Extra Python modules, undeclared modifications and mismatched patches fail.
- Public tokenizer data provisioned from a hash-pinned archive during the image
  build, not downloaded by a runtime compatibility check.
- Separate legacy and native capability profiles. A successful legacy import
  never means native Flows is available.
- A proposed manual-only production workflow. Production remains the legacy
  profile; it cannot consume the candidate image artifact.
- Executable production authorization and image-identity checks, with negative
  fixtures. Promotion reuses the checked image and selects its registry digest;
  it does not rebuild or update the mutable `latest` tag.

The native candidate does **not** implement a graph adapter, pilot flag, node
controls or editor preview yet. Its application still contains the existing
legacy executor. Do not send callers to it just because framework tests pass.

## Verified locally on 2026-11-03

| Check | Observed result | What it does not establish |
| --- | --- | --- |
| Release/provenance/image-promotion checks | 47 tests passed | No real Docker daemon, GitHub runner or Azure deployment was used |
| Existing native characterization suite | 30 tests passed; one `audioop` deprecation warning | These characterize framework behavior, including gaps; they do not fix repeated nodes or prove application-level safeguards |
| Installed package integrity | 555 recorded Python files checked; three declared overlays matched | This is the existing local installation, not the candidate image |
| Installed native runtime probe | Required native schemas and node/context APIs available; guard violations zero | Application provider startup, speech and business actions are not exercised |
| Custom source, legacy profile | Correct source selected; legacy import verified; guard violations zero | Native Flows support or full legacy call behavior |
| Custom source, native profile | Correctly rejected with exit 2: missing Flows; guard violations zero | No missing framework module was copied into the custom source |
| Workflow syntax | Both YAML documents parsed; 19 shell blocks passed `bash -n`; inline Python was compiled/exercised | Full GitHub Actions semantics and `actionlint` await CI |

Raw local results are retained under `generated-artifacts/voice-pilot/` in this
worktree and are excluded from Git and publishing. Re-run checks if the code or
the measured runtime changes; do not turn missing image evidence into a pass.

## Why this is not a small missing-package fix

The custom production tree differs from the installed release across 212 shared
Python files. Consequential native requirements include handler-capable base
schemas, context/tool-handler synchronization and `PipelineWorker`, not only
the presence of a `pipecat.flows` directory.

The installed development package is not pristine either: its wheel `RECORD`
revealed a modified Flux initializer and two added Flux TTS modules. A plain
install of the same version would omit those additions. The candidate overlays
reproduce that known local runtime; they are **not** proof that every production
customization has been ported.

Before native application integration, review and test at least:

1. Explicit Flux turn strategies, interruption controls and bot-speaking gates.
2. The application's private Flux override compatibility checks.
3. Token-mode TTS buffering, substitutions and direct-speech context ownership.
4. The changed `TTSSpeakFrame.append_to_context` default and existing manual
   transcript anchoring, to avoid duplicate or missing context.
5. Tool registration and context refresh through the real LLM service.
6. Playback-aware end/transfer handling; queued TTS is not completed speech.
7. The legacy voice-regression baseline against the actual image.

The SDK artifact is pinned. Other dependencies retain the production requirement
ranges for this preparation. CI records the complete resolved dependency list
and installation report. Review/freeze that resolution before calling the
candidate fully reproducible; a package version label is not sufficient.

## Running the next gate

Use **Voice flow candidate — build and offline checks only**
(`.github/workflows/voice-flow-candidate.yml`) on the isolated candidate branch,
not the production-release workflow.

The candidate job:

1. Runs the local guard and image-promotion tests and workflow lint.
2. Builds the separate candidate image.
3. Verifies release sources and Flux overlay hashes inside it.
4. Probes actual native APIs in a credential-free, network-disabled container.
5. Runs the existing native characterization suite in that same image, with
   test tools mounted read-only rather than installed into the runtime.
6. Records the dependency resolution and source manifest.

A **candidate-branch push or manual** run additionally retains that exact checked
image and its image ID, commit and explicit production-ineligibility metadata for
one day. Main-branch push and PR checks do not retain a large image. If the artifact
expires, build and check a new candidate; do not silently rebuild under old evidence.

Even a green candidate workflow does not replace the application/provider
startup and voice-customization checks above. Those must pass before declaring
the full runtime gate complete or implementing/activating the native adapter.

This workspace cannot execute Docker. Container checks run on GitHub Actions.
Managed Git and the GitHub CLI can work even if the connector SDK is unavailable;
never extract or print credentials. Record actual run results separately, and
do not infer image or voice compatibility from successful authorization.

## Proposed production safeguards — not activated

The proposed `deploy-voice.yml` removes automatic push releases. Its credential-
free job builds and probes the unchanged legacy Dockerfile, then exports that
exact image. The release job requires all of:

- Explicit manual dispatch from `refs/heads/main`.
- The exact full approved commit, matching the build.
- A successful build/check job and matching image ID, commit and legacy labels.
- The `voice-production` GitHub environment.
- Actual environment metadata showing independent required reviewers,
  `prevent_self_review=true`, and exactly one custom branch policy: branch `main`.
- A human acknowledgement that new calls are paused and active calls drained.

Missing/unreadable protection metadata fails before Azure authentication. An
environment name alone is not protection. Configure the server-side controls and
verify the approval behavior before adopting this workflow. The environment GET
response does not establish administrator-bypass configuration; that must also
be reviewed explicitly. Do not dispatch the production workflow as a test.

**The drain acknowledgement does not measure or drain calls.** With process-local
state and one replica, a container update can drop active calls. An operator must
verify the maintenance window, pause new inbound routing, confirm zero active
calls immediately before environment approval, and keep routing paused until
post-update health verification succeeds. No zero-downtime claim is made.

The image is pushed only after approval and referenced by immutable registry
digest. Replica settings remain one minimum/one maximum. A health response does
not bypass source, image, profile or approval checks.

## Azure staging prerequisites — separate approval required

Do not provision or route anything from this document alone. Before execution,
obtain approved resource identifiers, access, cost limits and a test window for:

- A distinct staging Container App and staging-scoped identity/credentials.
  Never reuse the production app destination or production deployment principal.
- An isolated synthetic-data store, not a copy of production guest data, and no
  access to production Key Vault credentials.
- A dedicated test number/callback hostname only if separately approved.
- Fake API/MCP/persistence/telephony boundaries first; separately approve any paid
  STT/LLM/TTS traffic or real third-party request.
- The retained, checked candidate image, verified by ID and registry digest.
  Do not rebuild a different image for the rehearsal.

The full pilot must subsequently add a limited graph adapter, explicit opt-in/
unsupported-graph rejection, scoped action reuse, node contracts, and the minimum
existing-editor preview. Verify accepted STT turns, private LLM guidance, allowed
tools, revisions/corrections, stale/duplicate results, truthful action outcomes,
bounded retries and single-owner TTS/terminal playback. Keep those checks separate
from framework capability tests.

For a staging failure: stop synthetic calls, retain sanitized evidence and revert
only staging to its previous immutable image (or stop the isolated app). Do not
change production routing or data. A later production proposal must record the
previous production digest, drain active calls before any cutover/rollback, and
restore inbound routing only after verification and operator approval.

## Current decision

**GO:** review the isolated changes and run the build-only candidate image gate.

**NO-GO:** native application activation, real Azure/audio claims, or production
promotion. The approved plan remains in progress at the image compatibility gate;
no node-repeat or stuck-node fix is claimed by this checkpoint.
