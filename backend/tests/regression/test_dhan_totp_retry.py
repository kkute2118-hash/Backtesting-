"""A transient "Invalid TOTP" must not kill a job that is otherwise ready.

Run directly:  python3 backend/tests/regression/test_dhan_totp_retry.py

Two history builds, seventeen minutes apart, with the same correct TOTP secret:
run 34012631615 logged in and downloaded 500 symbols; run 34013361263 was told
"Dhan rejected the token request: Invalid TOTP" and died before doing anything.
A secret is either right or wrong — it does not alternate — so the variable is
the 30-second window. A code minted with a moment left can expire in flight, and
Dhan's clock need not agree with ours to the second.

The cost of that is out of all proportion: the token step is the first thing a
run does, so a one-second race throws away the whole build.

So a TOTP rejection is retried in a *later* window, and only a TOTP rejection —
retrying "Token can be generated once every 2 minutes" would just burn the next
window too.
"""
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os, tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "1100000000")
os.environ["DHAN_PIN"] = "1234"
os.environ["DHAN_TOTP_SECRET"] = "JBSWY3DPEHPK3PXP"
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-totp-")

from app.engine import core

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# Never actually wait 30 seconds for a window; record that we would have.
slept = []
core.time.sleep = lambda seconds: slept.append(seconds)


class FakeLogin:
    """Dhan, scripted: `replies` are returned in order, one per attempt."""

    replies = []
    codes_seen = []

    def __init__(self, client_id):
        self.client_id = client_id

    def generate_token(self, pin, code):
        FakeLogin.codes_seen.append(code)
        return FakeLogin.replies[len(FakeLogin.codes_seen) - 1]


sys.modules["dhanhq"] = types.SimpleNamespace(DhanLogin=FakeLogin)

INVALID = {"status": "error", "message": "Invalid TOTP"}
RATE_LIMITED = {"status": "error", "message": "Token can be generated once every 2 minutes."}
GOOD = {"accessToken": "a-real-token"}


def run(replies):
    FakeLogin.replies = replies
    FakeLogin.codes_seen = []
    slept.clear()
    try:
        return core._dhan_generate_fresh_token(), None
    except Exception as exc:
        return None, exc


# ------------------------------------- 1. the incident: one rejection, then fine
token, err = run([INVALID, GOOD])
check("a single Invalid TOTP is retried, not fatal", token == "a-real-token",
      f"{err!r}" if err else token)
check("the retry used a second attempt", len(FakeLogin.codes_seen) == 2,
      str(len(FakeLogin.codes_seen)))
check("it waited for a new window before retrying", any(s > 1 for s in slept), str(slept))

# ----------------------------------------- 2. a genuinely wrong secret gives up
token, err = run([INVALID, INVALID, INVALID])
check("a secret that fails every window still fails", token is None and err is not None)
check("it stops at the attempt limit",
      len(FakeLogin.codes_seen) == core.DHAN_TOTP_ATTEMPTS, str(len(FakeLogin.codes_seen)))
check("and says the secret is the likely cause",
      err is not None and "secret" in str(err).lower(), str(err))

# ------------------------- 3. a rate-limit reply must NOT be retried into silence
token, err = run([RATE_LIMITED, GOOD])
check("a non-TOTP error is raised immediately", token is None and err is not None)
check("without burning a second attempt", len(FakeLogin.codes_seen) == 1,
      str(len(FakeLogin.codes_seen)))
check("and it reports what Dhan said",
      err is not None and "2 minutes" in str(err), str(err))

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
