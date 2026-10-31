# Session recovery self-review and delivery goal

## Scope

Recorded substantial-change self-review/checks/commit/push/container reporting in AGENTS.md and reviewed session/quota recovery, notification repair and archival. Preserve ports/domains/credentials/topology/media. Unfinished delivery-root FIFO and independent dirty changes were excluded. Earlier reports' uncommitted status described their own checkpoints.

## Review findings

- Actual problem: separate session/quota faults and recover original output first. Only provably missing-history read-only research may receive bounded replacement; unknown subtitles never replay.
- Removed unused early-observation API and one-time historical archival helper.
- Consolidated quota-budget reuse and lease/permission checks; removed duplicate coordinator waiting writes.
- Reused CodexClient, Records, supervisor, notification adapter and standard library. No new dependency/queue framework/table.
- Retained four runtime responsibilities: session state, coordination, terminal intents and archival intents. Current docs/history/manual files remain in required directories.
- Preserved original thread/turn/generation/input-policy/fingerprints/CAS/leases/locks without adoption/deletion authority.
- Fixed completed history occupying the bounded unknown-fence scan: reproduced 130 completed rows falsely blocking new work, then limited scan to truly unknown calls while still rejecting real unknowns.
- Excluded FIFO `runtime/state.py`, its docs/tests and three independent line-ending changes from commit/image.

## Results

Session observation/quota deadlines persist independently. Two-hour quota checks cap at ten and persist budget before calls; successful nonces without accepted progress do not reset it. Existing completed results can pass while new probes remain unavailable. Missing history allows three observations/one read-only replacement, retaining original unknown audit and rejecting late generations.

Only new explicit parent terminal events notify; child issues aggregate, old terminal history does not backfill. Cross-service semantics remain at least once. Accepted/terminal-evidenced Media threads archive only after unique-turn checks; unknown/running/manually extended threads remain.

Original task advanced 121/746 → 746/746, `completed_with_warnings`: 84 complete/662 review (553 uncertain, 97 old identification unknown, 12 old subtitle unknown). Original 121/final 746 results retained; 746 sources, 745 targets/745 hardlink identities and sampled SHA256 unchanged.

Cumulative 58 Media threads archived; zero attributable Media in the active list, fourteen unrelated entries untouched. Historical mistaken notifications stayed delivered 104/suppressed 16 without further backfill.

126 installed-package tests passed, plus seven after archival simplification. Earlier twelve JS, bilingual 320/390/768/1440 browser and LikeC4 passed. Final pre-push installed 126 passed again.

## Deployment and Git

NAS control/workers rebuilt through setup, installed/source parity, running/zero restarts, model/downloader checks passed. Cloud web/MCP were not rebuilt; public tasks assets still needed update. Codex/Quant/Crawler/Portal IDs/images/start times remained.

On cloud preserve existing `.env`, then:

```sh
git pull --ff-only
sh setup.sh cloud
```

No port/domain/FRP/proxy change or repeated NAS rebuild required. Documentation/rules alone require no rebuild. At that checkpoint 662 review files were media-result work, not automatically solved by rebuilding; later reports document recovery. Strict FIFO remained separate.

Stage only reviewed scope; inspect exact diff/secrets/untracked files/links/tests, commit existing main, push origin main and compare `git ls-remote` with HEAD. Final response supplies actual commit/push status. Private logs/backups/hashes remain ignored under `state/session-recovery-20261030`. See [earlier report](session-recovery-goal-20261030.md) and [structured evidence](session-recovery-20261030.json).
