# Design records

Everything here was written during the build and is kept as it was written.
Each status line describes the day the document was written, not today.
Where a record and the code disagree, the code wins. The current picture is in
[ARCHITECTURE.md](../../ARCHITECTURE.md) and [SPEC.md](../../SPEC.md).

## Specs

Short documents written before a phase: the problem, the measurements and the
decisions, with the alternatives that lost. If you read one, read the contact
feed. It shows the method: measure the heap, find the cause, move the work to
the side of the system that can afford it.

| Spec | What it decided |
|---|---|
| [Airspace overlay](specs/2026-08-04-airspace-overlay-design.md) | Drawing controlled airspace on the scope: the data pipeline, rendering, and the options considered and rejected |
| [Contact feed](specs/2026-08-08-contact-feed.md) | Moving filtering, sorting and capping from the board to the Pi, and a fixed 40-byte binary record in place of JSON |
| [Runtime site configuration](specs/2026-08-08-runtime-site-config-design.md) | Moving per-site data out of compiled headers. The Pi owns the config, and the board's NVS holds only enough to find the Pi |
| [Phase 4 scoping](specs/2026-08-08-phase4-scoping.md) | The browser config UI: Flask from apt, two services rather than one, and the preview as the feature |
| [Receiver installer](specs/2026-08-13-receiver-installer-design.md) | Rebuilding the receiver Pi from a bare image with one script, designed for a second operator who isn't the author |

## Plans

Step-by-step execution plans, one per phase. Claude Code ran them task by task
under my review, using the
[superpowers](https://github.com/obra/superpowers) workflow (hence the header
on each). They are long because they spell out every test and every expected
result in advance, and they predate the move of this folder, so their paths say
`docs/superpowers/`. They are a record of how the work ran, not reading
material. The specs above are the readable version.

- [v2 build](plans/2026-08-04-boxradar-v2-build.md): scope, datablocks, touch and polish on the new board
- [Airspace overlay](plans/2026-08-04-airspace-overlay.md)
- [METAR proxy](plans/2026-08-08-metar-proxy.md): weather served on demand by the Pi
- [Airspace selection](plans/2026-08-08-airspace-selection.md): airspace picked by config, not filtered by rule
- [Geography blob](plans/2026-08-08-geography-blob.md): the binary map format and its native-tested reader
- [Board blob loading](plans/2026-08-08-board-blob-loading.md): the board fetching and drawing from the blob
- [Receiver installer](plans/2026-08-13-receiver-installer.md)
