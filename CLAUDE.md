# Instructions for Claude sessions on this repository

## Oracle Cloud: Always Free only — never anything that can be billed

The owner's card is on file with Oracle Cloud. Everything created there must
stay inside Oracle's **Always Free** allowance, always:

- Only `VM.Standard.A1.Flex` (Ampere) — at most **4 OCPUs and 24 GB memory in
  total** across the whole tenancy — plus, if ever needed, the free
  `VM.Standard.E2.1.Micro`. No other shape.
- At most **200 GB of block storage in total**, boot volumes included.
- No paid services at all: no load balancers beyond the free one, no extra
  public IPs beyond ephemeral ones, no databases, no GPU, no autoscaling.
- Never upgrade the account to Pay As You Go, and never suggest it.
- `deploy/oracle/provision.py` enforces these limits against the tenancy's
  existing usage before creating anything. Do not weaken, bypass or raise
  those checks. If a task seems to need more, stop and ask the owner first.
- When unsure whether something is Always Free, treat it as paid and ask.
