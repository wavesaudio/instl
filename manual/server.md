# instl JSON-RPC server

The server exposes existing instl commands to local clients. It listens only on
IPv4 loopback, queues one command at a time, and launches every command in a new
instl subprocess. A fresh process is important because instl configuration is
global; reusing it inside a long-running, concurrent server would make commands
affect one another.

## Starting the server

Secure mode is the default:

```sh
instl server --secure
```

For explicit, unauthenticated local access:

```sh
instl server --insecure
```

The server chooses a free port unless `--port` is given. `--discovery-file` and
`--token-file` override their per-user defaults. `--history-limit` controls how
many completed jobs remain visible in memory and defaults to 25.

The discovery file is:

- macOS: `~/Library/Application Support/Waves Audio/instl/server.json`
- Windows: `%LOCALAPPDATA%\Waves Audio\instl\server.json`

It records the loopback address, selected port, security mode, monitoring URL,
and—in secure mode—the path of the token file. Writes are atomic. The discovery
directory, discovery file, and token file are restricted to the current OS user.
A lock prevents two default server instances from publishing the same discovery
file. A custom discovery/token parent directory must already be private to the
current user; do not place secure-mode files directly in a shared temporary
directory.

`--secure` means authenticated, same-machine, same-user IPC. It protects against
connections from other unprivileged OS users. It does not encrypt loopback
traffic and cannot protect against an administrator or another compromised
process running as the same user. Do not expose this HTTP endpoint on a network.
If remote operation is needed later, add a separate mutually authenticated TLS
gateway instead of changing this listener to bind a non-loopback address.

## Protocol

Send JSON-RPC 2.0 requests using HTTP `POST /rpc` and
`Content-Type: application/json`. Secure clients also send:

```text
Authorization: Bearer <contents of token_file>
```

Available methods:

| Method | Parameters | Result |
| --- | --- | --- |
| `system.ping` | `{}` | Server identity, PID, security mode, and time |
| `jobs.launch` | `{"args":[...], "cwd":"optional"}` | New queued job |
| `jobs.list` | `{}` | Jobs, newest first |
| `jobs.get` | `{"job_id":"..."}` | Current job state |
| `jobs.poll` | `{"job_id":"...", "after":0, "limit":500}` | State and ordered output events |
| `jobs.abort` | `{"job_id":"..."}` | Updated job state |

`args` contains the normal instl arguments after the executable name. It is
always passed as an argument array without a shell. Launching another `server`
command is rejected. Jobs move through `queued`, `running`, and a terminal state:
`succeeded`, `failed`, or `aborted`. While cancellation is in progress the state
is `aborting`.

Output events have monotonically increasing sequence numbers and a `stream` of
`stdout`, `stderr`, or `system`. The server retains up to 4 MiB of recent output
per job. A client that falls behind receives `events_dropped: true` and can
continue from `oldest_event`.

JSON-RPC itself has no standard output-streaming response. Polling keeps the
wire protocol standard, reconnectable, and simple; the supplied client polls at
150 ms and displays it as a live stream.

## C++ client

The client uses C++20, system sockets, the shared `fstring` types, and `jsonland`.
Build it with:

```sh
cmake -S instl_client -B build/instl-client
cmake --build build/instl-client --config Release
```

The build locates both shared libraries under `XPlatform/Utilities`. Override
`INSTL_UTILITIES_INCLUDE` or `INSTL_JSON_INCLUDE` only for a nonstandard tree.

Examples:

```sh
instl-client ping
instl-client run -- version --no-system-log
instl-client launch -- fail --sleep 30
instl-client list
instl-client abort JOB_ID
instl-client follow JOB_ID
instl-client monitor-url
```

Use `--discovery PATH` before the client command when the server uses a custom
discovery file. `run` returns the subprocess exit code. Pressing Ctrl-C while
following requests cancellation and continues monitoring until the server
confirms the terminal state.

## Monitoring page

Open the URL printed by `instl-client monitor-url`. The authentication token is
placed in the URL fragment, which browsers do not send in the HTTP request; the
page reads it and adds the authorization header to JSON-RPC calls. The page lists
jobs, tails their output, and can abort queued or running jobs.

The server rejects cross-origin browser requests and all mutating HTTP GETs. The
insecure option should still be limited to controlled development environments,
because any local native process can use it.
