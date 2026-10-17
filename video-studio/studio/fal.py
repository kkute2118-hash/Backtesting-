"""fal.ai queue client: submit a job, check on it, fetch the result."""
import os

import httpx

QUEUE = "https://queue.fal.run"


class FalError(RuntimeError):
    pass


class FalClient:
    def __init__(self, key=None, transport=None):
        self.key = key or os.environ.get("FAL_KEY", "")
        self.http = httpx.Client(timeout=60, transport=transport)

    def _headers(self):
        if not self.key:
            raise FalError("FAL_KEY is not set. Get a key at fal.ai/dashboard/keys.")
        return {"Authorization": f"Key {self.key}"}

    def _call(self, method, url, **kw):
        r = self.http.request(method, url, headers=self._headers(), **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise FalError(f"fal.ai {r.status_code}: {detail}")
        return r.json()

    def submit(self, endpoint, payload):
        """Queue a job. Returns fal's ids and the URLs to poll."""
        d = self._call("POST", f"{QUEUE}/{endpoint}", json=payload)
        return {"request_id": d["request_id"], "status_url": d["status_url"],
                "response_url": d["response_url"]}

    def status(self, status_url):
        """IN_QUEUE, IN_PROGRESS or COMPLETED, plus queue position if any."""
        return self._call("GET", status_url)

    def result(self, response_url):
        return self._call("GET", response_url)

    def download(self, url, path):
        with self.http.stream("GET", url) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
