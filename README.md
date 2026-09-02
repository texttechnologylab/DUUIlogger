# DUUI-Logging

Structured logging for **Docker Unified UIMA Interface (DUUI)** Python tool components. It lets a tool emit logs while 
handling a request and have them surfaced on the **Java side** printed to the DUUI console and saved in a connected
database.

---

## How it works 

Logs ride back on the `/v1/process` response instead of being pushed to Java live:

1. When DUUI wants logs it sets a `DUUI-Log-Collect: true` **request** header.
2. While the request is handled, everything you log is appended to a request-scoped buffer.
3. When the response is sent, the middleware serialises that buffer into a `DUUI-Logs`
   **response** header (JSON array format), which the Java driver reads off the HTTP response.

Important note: logs only surface when the request returns, **not** mid processing.

In addition to sending the logs to DUUI they are always printed in the containers
console in realtime.

---

## Installation

The package is hosted on GitHub. It is not yet on PyPI.

**With `uv`** . In your tool's `pyproject.toml`:

```toml
[project]
dependencies = ["duui-logging"]

[tool.uv.sources]
duui-logging = { git = "https://github.com/texttechnologylab/DUUIlogger" }
```

Then run `uv lock && uv sync`. To pin a revision, adjust the source and add `rev = "<git-tag-or-commit>"`:

```toml
[tool.uv.sources]
duui-logging = { git = "https://github.com/texttechnologylab/DUUIlogger", rev = "main" }
```

**With `pip`:**

```bash
pip install "git+https://github.com/texttechnologylab/DUUIlogger"
```

Requires Python ≥ 3.10. Pulls in `fastapi` and `pydantic`.

---

## Quick start

A minimal FastAPI-based DUUI tool. Two lines wire up logging; the rest is your component.

```python
import logging
from fastapi import FastAPI
import duui_logging
from duui_logging import log_info, log_warn, log_error

app = FastAPI()

# 1) Install the middleware. This is what collects a request's logs and returns them to
#    DUUI. `add_logging` also picks a default logger name (this file's module),
#    so log calls without an explicit `logger=` are tagged with your component name.
duui_logging.add_logging(app)

# 2) (optional but recommended) Also forward logs from third-party libraries + `warnings.warn`.
#    Call once at startup. See "Capturing third-party library logs" below.
duui_logging.install(level=logging.INFO)


@app.post("/v1/process")
async def process(request):
    log_info("started processing")

    if not request.text.strip():
        log_warn("document is empty")

    try:
        result = do_work(request.text)
    except Exception:
        log_error("processing failed")   # attaches the exception traceback automatically
        raise

    return result
```

Set the debug level in the DUUI composer to enable logging on the Java side. Logging is
**off by default** (`DebugLevel.NONE`); pick a level to turn it on:

```java
DUUILuaContext ctx = new DUUILuaContext().withJsonLibrary();

DUUIComposer composer = new DUUIComposer()
        .withSkipVerification(true)
        .withLuaContext(ctx)
        .withWorkers(1)
        .withDebugLevel(DUUIComposer.DebugLevel.TRACE)  // Set the level; logging is off (NONE) until you do
        .withComponentLogging(true)   // Collect logs from tool components. Default true
        .withDebugColorful(true)      // Color the console: INFO white, WARN yellow, ERROR red, CRITICAL bold-red. Default true
        .withDebugSeverity(true)      // Prefix each message with its level, e.g. [WARN]. Default true
        .withDebugSource(true);       // Prefix each message with [component | document]. Default true
```

Every toggle has a matching getter (`getDebugLevel()`, `isComponentLoggingEnabled()`,
`isColorfulLoggingEnabled()`, `isLoggingSeverityEnabled()`, `isLoggingSourceEnabled()`).

**What each does:**

| Method | Effect                                                                                                                                                                                 | Default |
|---|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|
| `withDebugLevel(level)` | Console threshold. Prints events **at least as severe** as `level` and suppresses the rest (e.g. `INFO` prints `INFO/WARN/ERROR/CRITICAL`, hides `TRACE/DEBUG`). `NONE` = logging off. | `NONE` |
| `withComponentLogging(false)` | Turn **off** collecting logs from tool components (stops sending the `DUUI-Log-Collect` header).                                                                                       | `true` (on) |
| `withDebugColorful(false)` | Turn **off** ANSI color — do this when writing to a file or a terminal that doesn't understand escape codes.                                                                           | `true` |
| `withDebugSeverity(true)` | Prefix component messages with their level, e.g. `[CRITICAL]`.                                                                                                                         | `true` |
| `withDebugSource(true)` | Prefix component messages with `[component key \| document id]` so you can tell where each line came from.                                                                             | `true` |

The `Colorful` / `Severity` / `Source` toggles only affect what the **console** renders; the
raw records are always kept in full (see below).

**Logs are also written to a connected database.** If the composer has a SQLite or MongoDB Database attached
the collected events land there too.

---

## Logging methods

All six helpers share the same signature and return the `LogRecord` they emitted. Import
them from the top-level package:

```python
from duui_logging import (
    log_trace, log_debug, log_info,
    log_warn, log_warning,   # log_warning is an alias for log_warn
    log_error, log_critical,
)
```

| Helper | Level | `withException` default | `withStacktrace` default |
|---|---|---|---|
| `log_trace(message="")` | `TRACE` | `False` | `20` |
| `log_debug(message)` | `DEBUG` | `False` | `0` |
| `log_info(message)` | `INFO` | `False` | `0` |
| `log_warn(message)` / `log_warning` | `WARN` | `False` | `0` |
| `log_error(message)` | `ERROR` | **`True`** | `0` |
| `log_critical(message)` | `CRITICAL` | **`True`** | `20` |

Levels map to DUUI's `DebugLevel` threshold on the Java side (ascending severity:
`TRACE < DEBUG < INFO < WARN < ERROR < CRITICAL`), so DUUI's configured level filters
which of these reach the console.

### Detailed usage information

Every helper takes the same keyword arguments:

```python
log_info(
    message: str,
    withTimeStamp: bool | int = True,
    withException: bool = False,   # True for log_error / log_critical
    withStacktrace: int = 0,       # 20 for log_trace / log_critical
    logger: str = "",
) -> LogRecord
```

**`message`**: the log text.

**`withTimeStamp`**: when the log happened.
- `True`: stamp with python's "now" (epoch millis).
- `False` / `0`: no timestamp (Java tags it with arrival time instead).
- any other integer to set your custom value.

**`withException`**: attach the traceback of the exception currently being handled. When
`True` and the call happens **inside an `except` block** (try / except), the real exception traceback is
attached. Default `True` for `log_error`/`log_critical` (the common case), `False` for the
rest. Outside an `except` block it has no effect.

**`withStacktrace`**: attach the current **call stack** (where the log call was made), even
when there is no exception. It's an `int`: `0` (or negative) disables it; any value `> 0` is
the number of most-recent frames to include. Built on `where_am_i`.

> If both a traceback and a call stack are requested, an **active exception traceback wins**.

**`logger`**: the logger name for this record. Don't set it to use the process wide default
(set by `add_logging` to your component's module name; otherwise `"duui"`).

### Examples

A complete example component can be found [here](https://github.com/texttechnologylab/DockerUnifiedUIMAInterface/tree/main/test_containers/python_logging/letter_counter).

```python
# Plain info
log_info("loaded model")

# Warning tagged with a specific logger, timestamped now
log_warn("input truncated to 512 tokens", logger="tokenizer", withTimeStamp=True)

# Error inside an except block — traceback attached automatically
try:
    risky()
except Exception:
    log_error("risky() failed")
    raise

# Attach a 10-frame call stack without any exception (useful for debugging control flow)
log_debug("reached checkpoint B", withStacktrace=10)

# Trace as a bare "I got here" marker (message optional, full stack by default)
log_trace()

# Set an explicit timestamp
log_info("Important log", withTimeStamp=1)
log_info("Important log", withTimeStamp=2)
```

---

## Capturing third-party library logs

The `log_*` helpers cover **your** code. To also collect logs by **third-party
libraries** through the standard `logging` module (and Python `warnings`), install the
bridge once at startup:

```python
import logging
import duui_logging

duui_logging.install(level=logging.INFO)
```

After this, any library that logs via stdlib `logging` like `logging.getLogger("torch")`,
is forwarded to DUUI too, with its numeric level mapped to the nearest DUUI level.

```python
duui_logging.install(
    level=logging.INFO,      # min level the root logger processes
    capture_warnings=True,   # also route warnings.warn(...) through logging
    keep_stderr=True,        # also keep printing to container console
) -> DUUICollectHandler
```

- **`level`**: records below this never reach any handler.
- **`capture_warnings`**: routes `warnings.warn(...)` (e.g. `DeprecationWarning`) through
  logging via `logging.captureWarnings(True)`.
- **`keep_stderr`**: keep the container's own console output in addition to forwarding.

`duui_logging.uninstall()` removes the handler again (mainly for tests).

Raw `print(...)` bypass the logging framework entirely. Use the `log_*` helpers or the
`logging` library to have output reach Java.

---

## The middleware

`add_logging(app)` installs `DUUILoggingMiddleware` and resolves a default logger name
from the calling file. Equivalent long forms:

```python
# Preferred: picks the default logger name (this file's module) automatically.
duui_logging.add_logging(app, max_bytes=16_000, default_logger=None)

# Manual: you must pass default_logger yourself, or log calls without logger= fall back to "duui".
app.add_middleware(duui_logging.DUUILoggingMiddleware, default_logger="my-tool")
```

**`max_bytes`** (default `16_000`) caps the `DUUI-Logs` response header so it stays under
common server/client limits. When the buffered logs exceed it, the middleware first sheds
stacktraces, then drops the oldest records (keeping the most recent), inserting a
`[duui_logging] dropped N earlier log line(s)` marker.

---

## API reference

Everything below is importable from the top-level `duui_logging` package.

| Name | Kind | Purpose |
|---|---|---|
| `log_trace` / `log_debug` / `log_info` / `log_warn` / `log_warning` / `log_error` / `log_critical` | function | emit a structured log record |
| `where_am_i` | function | current call stack as a string |
| `current_exception_trace` | function | traceback of the active exception, or `None` |
| `add_logging` | function | install the middleware + pick a default logger name |
| `install` / `uninstall` | function | bridge stdlib `logging` + `warnings` into the buffer |
| `DUUILoggingMiddleware` | class | the middleware that returns logs to Java |
| `DUUICollectHandler` | class | the `logging.Handler` `install` attaches |
| `ErrorLevel` | enum | the six level names |
| `LogRecord` | model | the wire format shared with Java |


# Cite
If you want to use the project please quote this as follows:

Alexander Leonhardt, Giuseppe Abrami, Daniel Baumartz and Alexander Mehler. (2023). "Unlocking the Heterogeneous Landscape of Big Data NLP with DUUI." Findings of the Association for Computational Linguistics: EMNLP 2023, 385–399. [[LINK](https://aclanthology.org/2023.findings-emnlp.29)] [[PDF](https://aclanthology.org/2023.findings-emnlp.29.pdf)]

Daniel Bundan, Giuseppe Abrami (2026). "DUUI Logging". [[LINK](https://github.com/texttechnologylab/DUUIlogger)]

## BibTeX
```
@inproceedings{Leonhardt:et:al:2023,
  title     = {Unlocking the Heterogeneous Landscape of Big Data {NLP} with {DUUI}},
  author    = {Leonhardt, Alexander and Abrami, Giuseppe and Baumartz, Daniel and Mehler, Alexander},
  editor    = {Bouamor, Houda and Pino, Juan and Bali, Kalika},
  booktitle = {Findings of the Association for Computational Linguistics: EMNLP 2023},
  year      = {2023},
  address   = {Singapore},
  publisher = {Association for Computational Linguistics},
  url       = {https://aclanthology.org/2023.findings-emnlp.29},
  pages     = {385--399},
  pdf       = {https://aclanthology.org/2023.findings-emnlp.29.pdf},
  abstract  = {Automatic analysis of large corpora is a complex task, especially
               in terms of time efficiency. This complexity is increased by the
               fact that flexible, extensible text analysis requires the continuous
               integration of ever new tools. Since there are no adequate frameworks
               for these purposes in the field of NLP, and especially in the
               context of UIMA, that are not outdated or unusable for security
               reasons, we present a new approach to address the latter task:
               Docker Unified UIMA Interface (DUUI), a scalable, flexible, lightweight,
               and feature-rich framework for automatic distributed analysis
               of text corpora that leverages Big Data experience and virtualization
               with Docker. We evaluate DUUI{'}s communication approach against
               a state-of-the-art approach and demonstrate its outstanding behavior
               in terms of time efficiency, enabling the analysis of big text
               data.}
}

@misc{Bundan:Abrami:2026,
  title     = {DUUI Logging},
  author    = {Bundan, Daniel and Abrami, Giuseppe},
  year      = {2026},
  month     = {Aug},
  url       = {https://github.com/texttechnologylab/DUUIlogger}
}
```
