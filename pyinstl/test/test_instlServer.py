import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

from pyinstl.instlServer import InstlHttpServer, JobManager


HELPER_CODE = r"""
import sys
import time

if sys.argv[1] == "emit":
    print("standard output", flush=True)
    print("standard error", file=sys.stderr, flush=True)
elif sys.argv[1] == "sleep":
    print("sleeping", flush=True)
    time.sleep(30)
elif sys.argv[1] == "fail":
    print("failed", file=sys.stderr, flush=True)
    raise SystemExit(7)
"""


def wait_for_job(manager, job_id, wanted_statuses, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = manager.get_summary({"job_id": job_id})
        if result["status"] in wanted_statuses:
            return result
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {wanted_statuses}")


class JobManagerTest(unittest.TestCase):
    def setUp(self):
        self.manager = JobManager([sys.executable, "-u", "-c", HELPER_CODE], 10)

    def tearDown(self):
        self.manager.close()

    def test_captures_both_output_streams(self):
        job = self.manager.launch({"args": ["emit"]})
        completed = wait_for_job(self.manager, job["job_id"], {"succeeded", "failed"})
        self.assertEqual("succeeded", completed["status"])
        polled = self.manager.poll({"job_id": job["job_id"], "after": 0})
        output = {(event["stream"], event["text"]) for event in polled["events"]}
        self.assertIn(("stdout", "standard output\n"), output)
        self.assertIn(("stderr", "standard error\n"), output)

    def test_preserves_failure_exit_code(self):
        job = self.manager.launch({"args": ["fail"]})
        completed = wait_for_job(self.manager, job["job_id"], {"failed"})
        self.assertEqual(7, completed["return_code"])

    def test_aborts_running_process(self):
        job = self.manager.launch({"args": ["sleep"]})
        wait_for_job(self.manager, job["job_id"], {"running"})
        self.manager.abort({"job_id": job["job_id"]})
        completed = wait_for_job(self.manager, job["job_id"], {"aborted"})
        self.assertNotEqual(0, completed["return_code"])


class AuthenticatedHttpTest(unittest.TestCase):
    def setUp(self):
        self.manager = JobManager([sys.executable, "-u", "-c", HELPER_CODE], 10)
        self.server = InstlHttpServer(("127.0.0.1", 0), self.manager, "test-token", "test-instance")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/rpc"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.manager.close()

    def request(self, token=None):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "system.ping"}).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return urllib.request.urlopen(urllib.request.Request(self.url, body, headers), timeout=2)

    def test_requires_and_accepts_token(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request()
        self.assertEqual(401, raised.exception.code)

        with self.request("test-token") as response:
            result = json.load(response)["result"]
        self.assertEqual("test-instance", result["instance_id"])
        self.assertEqual("token", result["security"])


if __name__ == "__main__":
    unittest.main()
