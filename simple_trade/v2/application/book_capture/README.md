# Sampled Book Capture

Status: implemented and locally tested on 2026-09-23. Not deployed or enabled
in production. This is a data-input foundation, not an automatic trading loop.

## Enablement

- 未设置 `V2_BOOK_CAPTURE_PATH` 和 `V2_BOOK_CAPTURE_CONFIG` 时关闭。
- To enable after deployment approval, configure an absolute path to a dedicated
  capture SQLite file. Its parent directory must already exist and be writable.
- Never use the trading database path. Existing non-capture databases are rejected.
- Start and stop the backend through the repository's existing `.sh` scripts.
- Clearing the variable and restarting disables capture. No real or broker-paper
  orders are placed by this component, regardless of capture configuration.

旧路径变量沿用默认值；也可用 `V2_BOOK_CAPTURE_CONFIG` 指向绝对路径 JSON，显式配置采样与容量。两个变量同时存在时路径必须一致。详见 `../paper_session/PREFLIGHT.md`。未显式设置的字段仍使用以下默认值：

| Setting | Default |
| --- | --- |
| Selected HK stocks | 8 |
| Minimum sampling interval per stock | 500 ms |
| Target refresh | 30 s |
| In-memory queue | 2,048 records |
| Write batch | 128 records |
| Archive record limit | 1,000,000 |
| Main database file limit | 256 MiB |
| Minimum available disk space | 256 MiB |
| Subscription I/O wait budget | 8 s |

The file limit does not include transient SQLite rollback journals. Provision
additional disk headroom. There is no automatic history deletion or retention
rotation: capacity or persistent write failures stop capture and report an error.

## Data and Isolation

Known positions and open orders have priority, followed by today's confirmed
candidates ordered by the existing score. Shadow confirmations may be sampled;
this does not make them eligible for formal alerts or trading.

ORDER_BOOK pushes supply only the sampled best bid/ask here. SDK callbacks do
bounded memory work; a separate writer batches records into the dedicated file.
Capture is not injected into the production feature engine or strategy event bus.
Capture failure is isolated from the existing quote and alert runtime.

Subscriptions use shared quota without evicting QUOTE or TICKER subscriptions.
Rotation releases only capture-owned book subscriptions after at least 65 seconds.
Borrowed subscriptions are not released. Shutdown detaches the sink but does not
unsubscribe remaining books, avoiding premature or shared-owner removal.

The feed's two side timestamps are Futu server receipt times, not exchange event
times. Missing values are not replaced with local receipt time. See the
[official push contract](https://openapi.futunn.com/futu-api-doc/quote/update-order-book.html).

## Inspection and Replay Boundaries

From the repository root, inspect an archive without starting the SDK:

```bash
bash scripts/run_book_capture_check.sh --db /absolute/path/book-capture.sqlite
```

The bounded, read-only command reports sessions and per-stock record coverage.
Runtime snapshots also expose `book_capture` with target/subscribed/pending lists,
received, sampled-out, invalid, dropped, persisted, connection changes and errors.

- `sampled_out` is deliberate rate limiting, not queue loss.
- `dropped` identifies known capture losses; reconnects also mark discontinuity.
- `closed_cleanly` means an orderly error-free close, not complete market coverage.
  Inspect dropped/invalid counts, connection changes and pending stocks separately.
- An unclosed session or error must not be presented as a complete replay sample.
- The current health view has a global last-receipt timestamp, not per-stock silence
  detection. Neither subscriptions nor zero reported drops prove lossless transport.

`to_paper_book` requires explicit `allow_sampled_server_time=True` and a caller-
supplied, independently verified `market_open` flag. Missing, stale, future,
crossed, empty or gap-marked books are rejected. The legacy `PaperBook.exchange_time`
field receives the older of the two server timestamps as a conservative proxy,
not a newly discovered exchange timestamp. Session-level health must also be
checked by a replay orchestrator.

This conversion does not send orders or guarantee fills. It cannot model full
depth, queue position, unsampled updates or real execution latency. An optional
local paper experiment now consumes committed captures; see
`../paper_session/README.md`. Calendar/fee validation, production acceptance,
out-of-sample evaluation and a frontend trading ledger remain separate work.

## Verification

The V2 and affected market-data/subscription suites passed 491 tests and 24 subtests
locally, including capacity, low disk, write failure, reconnect, subscription
ownership, callback isolation and strict paper-input checks. Live OpenD/production
connectivity and full-session load validation have not been performed this round.
