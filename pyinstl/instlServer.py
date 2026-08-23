"""Local JSON-RPC server for launching and monitoring instl commands.

The transport is deliberately small: HTTP on IPv4 loopback.  Secure mode adds
a random bearer token stored in a per-user, access-restricted file.  Each job is
run in a fresh instl subprocess because instl's configuration stack is global
and is not safe to reuse concurrently in a long-running process.
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import hmac
import http.server
import json
import logging
import os
import queue
import secrets
import signal
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import psutil


log = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 1024 * 1024
MAX_EVENTS_PER_JOB = 10_000
MAX_EVENT_BYTES_PER_JOB = 4 * 1024 * 1024
TERMINAL_STATES = frozenset(("succeeded", "failed", "aborted"))


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def default_server_dir() -> Path:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA is required to locate instl server discovery")
        return Path(local_app_data, "Waves Audio", "instl")
    return Path.home() / "Library" / "Application Support" / "Waves Audio" / "instl"


def _restrict_path_to_current_user(path: Path) -> None:
    """Apply owner-only permissions, failing closed on Windows."""
    if sys.platform != "win32":
        # Directories need execute permission for traversal.
        permissions = 0o600
        if path.is_dir():
            permissions = 0o700
        path.chmod(permissions)
        return

    try:
        import win32api
        import win32con
        import win32security

        process_token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
        )
        user_sid = win32security.GetTokenInformation(
            process_token, win32security.TokenUser
        )[0]
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(
            win32security.ACL_REVISION, win32con.GENERIC_ALL, user_sid
        )
        security_info = (
            win32security.OWNER_SECURITY_INFORMATION
            | win32security.DACL_SECURITY_INFORMATION
            | getattr(win32security, "PROTECTED_DACL_SECURITY_INFORMATION", 0x80000000)
        )
        win32security.SetNamedSecurityInfo(
            os.fspath(path),
            win32security.SE_FILE_OBJECT,
            security_info,
            user_sid,
            None,
            dacl,
            None,
        )
    except Exception as ex:
        raise RuntimeError(f"cannot restrict access to {path}: {ex}") from ex


def _ensure_private_directory(path: Path) -> None:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    if existed:
        if sys.platform == "win32":
            # LOCALAPPDATA is per-user. Do not replace the ACL of an arbitrary
            # existing parent supplied through --discovery-file.
            return
        path_stat = path.stat()
        if path_stat.st_uid != os.getuid() or stat.S_IMODE(path_stat.st_mode) & 0o077:
            raise RuntimeError(f"server directory must already be owner-only: {path}")
    _restrict_path_to_current_user(path)


def _atomic_write(path: Path, content: str) -> None:
    _ensure_private_directory(path.parent)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _restrict_path_to_current_user(temporary)
        os.replace(temporary, path)
        _restrict_path_to_current_user(path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class InstanceLock:
    """A small cross-platform advisory lock held for the server lifetime."""

    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def acquire(self, instance_id: str) -> None:
        _ensure_private_directory(self.path.parent)
        self.stream = open(self.path, "a+b")
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as ex:
            self.stream.close()
            self.stream = None
            raise RuntimeError(
                f"another instl server owns discovery file {self.path.with_suffix('.json')}"
            ) from ex
        self.stream.seek(0)
        self.stream.truncate()
        self.stream.write(f"{os.getpid()} {instance_id}\n".encode("ascii"))
        self.stream.flush()
        _restrict_path_to_current_user(self.path)

    def close(self) -> None:
        if self.stream is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None


@dataclasses.dataclass
class Job:
    job_id: str
    args: list[str]
    cwd: str | None
    created_at: str = dataclasses.field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    status: str = "queued"
    return_code: int | None = None
    abort_requested: bool = False
    process: subprocess.Popen[str] | None = dataclasses.field(default=None, repr=False)
    events: collections.deque = dataclasses.field(default_factory=collections.deque, repr=False)
    event_bytes: int = dataclasses.field(default=0, repr=False)
    next_event: int = 1

    def add_event(self, stream: str, text: str) -> None:
        event = {"seq": self.next_event, "time": utc_now(), "stream": stream, "text": text}
        event_size = len(text.encode("utf-8", errors="replace"))
        while self.events and (
            len(self.events) >= MAX_EVENTS_PER_JOB
            or self.event_bytes + event_size > MAX_EVENT_BYTES_PER_JOB
        ):
            removed = self.events.popleft()
            self.event_bytes -= len(removed["text"].encode("utf-8", errors="replace"))
        self.events.append(event)
        self.event_bytes += event_size
        self.next_event += 1

    def summary(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "args": list(self.args),
            "cwd": self.cwd,
            "status": self.status,
            "return_code": self.return_code,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "next_event": self.next_event,
        }


class RpcFault(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class JobManager:
    """Owns a single worker queue and all mutable job state."""

    def __init__(self, launch_prefix: list[str], history_limit: int):
        self.launch_prefix = list(launch_prefix)
        self.history_limit = history_limit
        self.jobs: collections.OrderedDict[str, Job] = collections.OrderedDict()
        self.lock = threading.RLock()
        self.pending: queue.Queue[Job | None] = queue.Queue()
        # Serialize installer jobs so two installs cannot modify the same files.
        self.worker = threading.Thread(target=self._work, name="instl-server-worker", daemon=True)
        self.worker.start()

    def launch(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise RpcFault(-32602, "params must be an object")
        args = params.get("args")
        cwd = params.get("cwd")
        if not isinstance(args, list) or not args or not all(isinstance(arg, str) for arg in args):
            raise RpcFault(-32602, "args must be a non-empty array of strings")
        if any("\0" in arg for arg in args) or sum(len(arg) for arg in args) > 256 * 1024:
            raise RpcFault(-32602, "args are too large or contain a NUL character")
        if args[0].lower() == "server":
            raise RpcFault(-32602, "a server job cannot launch another server")
        if cwd is not None:
            if not isinstance(cwd, str) or not Path(cwd).is_dir():
                raise RpcFault(-32602, "cwd must name an existing directory")
            cwd = os.fspath(Path(cwd).resolve())

        job = Job(job_id=uuid.uuid4().hex, args=list(args), cwd=cwd)
        with self.lock:
            self._prune_locked()
            self.jobs[job.job_id] = job
        self.pending.put(job)
        return job.summary()

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.lock:
            return [job.summary() for job in reversed(self.jobs.values())]

    def get(self, job_id: Any) -> Job:
        if not isinstance(job_id, str):
            raise RpcFault(-32602, "job_id must be a string")
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise RpcFault(-32004, f"unknown job {job_id}")
            return job

    def get_summary(self, params: Any) -> dict[str, Any]:
        return self.get(_job_id_from_params(params)).summary()

    def poll(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise RpcFault(-32602, "params must be an object")
        job = self.get(params.get("job_id"))
        after = params.get("after", 0)
        limit = params.get("limit", 500)
        if not isinstance(after, int) or after < 0:
            raise RpcFault(-32602, "after must be a non-negative integer")
        if not isinstance(limit, int) or not 1 <= limit <= 2000:
            raise RpcFault(-32602, "limit must be between 1 and 2000")
        with self.lock:
            oldest = job.next_event
            if job.events:
                oldest = job.events[0]["seq"]
            events = [event.copy() for event in job.events if event["seq"] > after][:limit]
            result = job.summary()
            result.update(
                {
                    "events": events,
                    "events_dropped": after + 1 < oldest,
                    "oldest_event": oldest,
                }
            )
            return result

    def abort(self, params: Any) -> dict[str, Any]:
        job = self.get(_job_id_from_params(params))
        process = None
        with self.lock:
            if job.status in TERMINAL_STATES:
                return job.summary()
            if job.process is not None and job.process.poll() is not None:
                # The worker will publish the natural terminal state momentarily.
                return job.summary()
            job.abort_requested = True
            job.add_event("system", "abort requested\n")
            if job.status == "queued":
                job.status = "aborted"
                job.finished_at = utc_now()
            else:
                job.status = "aborting"
                process = job.process
        if process is not None:
            threading.Thread(
                target=self._terminate_process_tree,
                args=(process,),
                name=f"abort-{job.job_id[:8]}",
                daemon=True,
            ).start()
        return job.summary()

    def close(self) -> None:
        with self.lock:
            active = [job for job in self.jobs.values() if job.status not in TERMINAL_STATES]
        for job in active:
            self.abort({"job_id": job.job_id})
        self.pending.put(None)
        self.worker.join(timeout=5)

    def _prune_locked(self) -> None:
        terminal = [job_id for job_id, job in self.jobs.items() if job.status in TERMINAL_STATES]
        excess = len(terminal) - self.history_limit + 1
        for job_id in terminal[:max(0, excess)]:
            del self.jobs[job_id]

    def _work(self) -> None:
        while True:
            job = self.pending.get()
            if job is None:
                return
            with self.lock:
                if job.abort_requested:
                    continue
                job.status = "running"
                job.started_at = utc_now()
            self._run(job)

    def _run(self, job: Job) -> None:
        # Never use a shell; RPC arguments map directly to the instl argument vector.
        command = self.launch_prefix + job.args
        popen_args: dict[str, Any] = {
            "args": command,
            "cwd": job.cwd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "backslashreplace",
            "bufsize": 1,
            "env": {**os.environ, "PYTHONUNBUFFERED": "1"},
        }
        if sys.platform == "win32":
            popen_args["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_args["start_new_session"] = True

        try:
            process = subprocess.Popen(**popen_args)
            with self.lock:
                job.process = process
                job.add_event("system", f"started pid {process.pid}\n")
                abort_now = job.abort_requested
            if abort_now:
                self._terminate_process_tree(process)

            readers = [
                threading.Thread(target=self._read_stream, args=(job, "stdout", process.stdout), daemon=True),
                threading.Thread(target=self._read_stream, args=(job, "stderr", process.stderr), daemon=True),
            ]
            for reader in readers:
                reader.start()
            return_code = process.wait()
            for reader in readers:
                reader.join()
            with self.lock:
                job.return_code = return_code
                if job.abort_requested:
                    job.status = "aborted"
                elif return_code == 0:
                    job.status = "succeeded"
                else:
                    job.status = "failed"
                job.finished_at = utc_now()
                job.process = None
                job.add_event("system", f"finished with exit code {return_code}\n")
        except Exception as ex:
            with self.lock:
                if job.abort_requested:
                    job.status = "aborted"
                else:
                    job.status = "failed"
                job.finished_at = utc_now()
                job.process = None
                job.add_event("system", f"could not run subprocess: {ex}\n")

    def _read_stream(self, job: Job, stream_name: str, stream) -> None:
        if stream is None:
            return
        try:
            for line in iter(lambda: stream.readline(64 * 1024), ""):
                with self.lock:
                    job.add_event(stream_name, line)
        finally:
            stream.close()

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            parent = psutil.Process(process.pid)
            processes = parent.children(recursive=True) + [parent]
            for child in reversed(processes):
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            _, alive = psutil.wait_procs(processes, timeout=3)
            for child in alive:
                try:
                    child.kill()
                except psutil.Error:
                    pass
        except psutil.Error:
            try:
                process.kill()
            except OSError:
                pass


def _job_id_from_params(params: Any) -> Any:
    if not isinstance(params, dict):
        raise RpcFault(-32602, "params must be an object")
    return params.get("job_id")


MONITOR_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>instl server</title><style>
body{font:14px system-ui;margin:20px;color:#202124}button{margin:2px}table{border-collapse:collapse;width:100%}
th,td{padding:6px;border-bottom:1px solid #ddd;text-align:left}tr.job{cursor:pointer}tr.job:hover{background:#f4f6f8}
#output{white-space:pre-wrap;background:#111;color:#ddd;padding:12px;min-height:240px;max-height:55vh;overflow:auto}
.stderr{color:#ff8c8c}.system{color:#8cc8ff}.running,.queued,.aborting{color:#986b00}.failed,.aborted{color:#b00020}.succeeded{color:#087c32}
</style></head><body><h1>instl server</h1><p id="server"></p><button id="refresh">Refresh</button>
<button id="abort" disabled>Abort selected</button><table><thead><tr><th>Job</th><th>Command</th><th>Status</th><th>Exit</th><th>Created</th></tr></thead><tbody id="jobs"></tbody></table>
<h2 id="selected">Output</h2><div id="output"></div><script>
let token=decodeURIComponent(location.hash.slice(1)), selected=null, after=0, rpcId=0;
async function rpc(method,params={}){let h={'Content-Type':'application/json'};if(token)h.Authorization='Bearer '+token;
 let r=await fetch('/rpc',{method:'POST',headers:h,body:JSON.stringify({jsonrpc:'2.0',id:++rpcId,method,params})});
 if(r.status===401){token=prompt('Authentication token:')||'';if(token)location.hash=encodeURIComponent(token);throw Error('authentication required')}
 let j=await r.json();if(j.error)throw Error(j.error.message);return j.result}
function cell(row,text,cls=''){let c=row.insertCell();c.textContent=text??'';c.className=cls;return c}
async function refresh(){try{let ping=await rpc('system.ping');document.getElementById('server').textContent=`PID ${ping.pid} · ${ping.security}`;
 let list=await rpc('jobs.list'), body=document.getElementById('jobs');body.textContent='';for(let j of list){let r=body.insertRow();r.className='job';r.onclick=()=>select(j.job_id);
 cell(r,j.job_id.slice(0,8));cell(r,j.args.join(' '));cell(r,j.status,j.status);cell(r,j.return_code);cell(r,j.created_at)}if(selected)await poll()}catch(e){document.getElementById('server').textContent=e}}
function select(id){selected=id;after=0;document.getElementById('output').textContent='';document.getElementById('selected').textContent='Output · '+id;document.getElementById('abort').disabled=false;poll()}
async function poll(){if(!selected)return;let j=await rpc('jobs.poll',{job_id:selected,after,limit:1000});for(let e of j.events){let s=document.createElement('span');s.className=e.stream;s.textContent=e.text;document.getElementById('output').appendChild(s);after=e.seq}
 document.getElementById('output').scrollTop=document.getElementById('output').scrollHeight;document.getElementById('abort').disabled=['succeeded','failed','aborted'].includes(j.status)}
document.getElementById('refresh').onclick=refresh;document.getElementById('abort').onclick=async()=>{if(selected){await rpc('jobs.abort',{job_id:selected});refresh()}};refresh();setInterval(refresh,1000);
</script></body></html>"""


class InstlRequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = "instl-json-rpc/1"

    def log_message(self, format_string: str, *args) -> None:
        log.debug("server HTTP: " + format_string, *args)

    @property
    def app(self) -> "InstlHttpServer":
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path not in ("", "/", "/index.html"):
            self.send_error(404)
            return
        body = MONITOR_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if urllib.parse.urlsplit(self.path).path != "/rpc":
            self.send_error(404)
            return
        if not self._valid_browser_origin():
            self.send_error(403, "cross-origin requests are not allowed")
            return
        if self.app.token is not None:
            # Compare tokens in constant time.
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {self.app.token}"
            if not hmac.compare_digest(supplied, expected):
                self.send_response(401)
                self.send_header("WWW-Authenticate", "Bearer")
                self.send_header("Content-Length", "0")
                self._security_headers()
                self.end_headers()
                return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        # Requiring JSON also blocks ordinary cross-site HTML form submissions.
        if content_type != "application/json":
            self.send_error(415, "Content-Type must be application/json")
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "invalid Content-Length")
            return
        if not 0 < content_length <= MAX_REQUEST_BYTES:
            self.send_error(413, "invalid request size")
            return
        try:
            request = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            return

        response = self.app.dispatch(request)
        if response is None:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self._security_headers()
            self.end_headers()
        else:
            self._json_response(response)

    def _valid_browser_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            parsed = urllib.parse.urlsplit(origin)
            return parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost") and parsed.port == self.app.server_port
        except ValueError:
            return False

    def _json_response(self, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'")
        self.send_header("Connection", "close")


class InstlHttpServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, manager: JobManager, token: str | None, instance_id: str):
        self.manager = manager
        self.token = token
        self.instance_id = instance_id
        super().__init__(address, InstlRequestHandler)

    def dispatch(self, request: Any) -> dict[str, Any] | None:
        request_id = None
        if isinstance(request, dict):
            request_id = request.get("id")
        is_notification = isinstance(request, dict) and "id" not in request
        try:
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                raise RpcFault(-32600, "invalid request")
            method = request["method"]
            params = request.get("params", {})

            security = "none"
            if self.token:
                security = "token"

            def ping(unused):
                del unused
                return {
                    "instance_id": self.instance_id,
                    "pid": os.getpid(),
                    "security": security,
                    "time": utc_now(),
                }

            # Keep the public RPC surface explicit and easy to audit.
            handlers = {
                "system.ping": ping,
                "jobs.launch": self.manager.launch,
                "jobs.list": lambda unused: self.manager.list_jobs(),
                "jobs.get": self.manager.get_summary,
                "jobs.poll": self.manager.poll,
                "jobs.abort": self.manager.abort,
            }
            handler = handlers.get(method)
            if handler is None:
                raise RpcFault(-32601, f"method not found: {method}")
            result = handler(params)
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcFault as ex:
            error = {"code": ex.code, "message": ex.message}
            if ex.data is not None:
                error["data"] = ex.data
            return {"jsonrpc": "2.0", "id": request_id, "error": error}
        except Exception:
            log.exception("unexpected JSON-RPC error")
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "internal error"}}


def run_instl_server(options, launch_prefix: list[str]) -> None:
    if not 0 <= options.server_port <= 65535:
        raise ValueError("server port must be between 0 and 65535")
    if options.server_history_limit < 1:
        raise ValueError("server history limit must be at least 1")

    server_dir = default_server_dir()
    discovery_path = server_dir / "server.json"
    if options.server_discovery_file:
        discovery_path = Path(options.server_discovery_file).expanduser()

    token_path = discovery_path.with_name("server.token")
    if options.server_token_file:
        token_path = Path(options.server_token_file).expanduser()
    if discovery_path.resolve() == token_path.resolve():
        raise ValueError("discovery file and token file must be different paths")
    lock = InstanceLock(discovery_path.with_suffix(".lock"))
    instance_id = uuid.uuid4().hex
    manager = None
    httpd = None
    token = None
    if options.server_secure:
        token = secrets.token_urlsafe(32)
    previous_signal_handlers = {}
    lock.acquire(instance_id)
    try:
        manager = JobManager(launch_prefix, options.server_history_limit)
        if token is not None:
            _atomic_write(token_path, token + "\n")
        httpd = InstlHttpServer(("127.0.0.1", options.server_port), manager, token, instance_id)
        port = httpd.server_port
        security = "none"
        if token:
            security = "token"

        # Publish only connection metadata; the token stays in its own file.
        discovery = {
            "version": 1,
            "instance_id": instance_id,
            "pid": os.getpid(),
            "started_at": utc_now(),
            "transport": "http-loopback",
            "protocol": "json-rpc-2.0",
            "host": "127.0.0.1",
            "port": port,
            "rpc_url": f"http://127.0.0.1:{port}/rpc",
            "monitor_url": f"http://127.0.0.1:{port}/",
            "security": security,
        }
        if token is not None:
            discovery["token_file"] = os.fspath(token_path.resolve())
        _atomic_write(discovery_path, json.dumps(discovery, indent=2) + "\n")

        print(f"instl server listening on 127.0.0.1:{port}", flush=True)
        print(f"discovery file: {discovery_path.resolve()}", flush=True)
        print(f"security: {discovery['security']}", flush=True)
        print(f"monitor: {discovery['monitor_url']}", flush=True)

        def request_shutdown(signum, frame):
            del signum, frame
            threading.Thread(target=httpd.shutdown, name="instl-server-shutdown", daemon=True).start()

        if threading.current_thread() is threading.main_thread():
            for signal_number in (signal.SIGINT, signal.SIGTERM):
                previous_signal_handlers[signal_number] = signal.getsignal(signal_number)
                signal.signal(signal_number, request_shutdown)
        httpd.serve_forever(poll_interval=0.25)
        print("instl server stopping", flush=True)
    finally:
        for signal_number, previous_handler in previous_signal_handlers.items():
            signal.signal(signal_number, previous_handler)
        if httpd is not None:
            httpd.server_close()
        if manager is not None:
            manager.close()
        try:
            current = json.loads(discovery_path.read_text(encoding="utf-8"))
            if current.get("instance_id") == instance_id:
                discovery_path.unlink(missing_ok=True)
                if token is not None:
                    token_path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass
        lock.close()
