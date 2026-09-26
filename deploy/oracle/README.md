# Running ATI Lab on Oracle Cloud's free tier

Oracle's **Always Free** Ampere server (up to 4 CPU cores and 24 GB of RAM,
free indefinitely) runs the whole app on one machine. Compared with Render's
free plan it never sleeps, has a real disk that survives restarts, and has
roughly 40 times the memory.

Everything is started by one script, `cloud-init.sh`, which you paste in while
creating the server. You need an Oracle Cloud account first
(<https://signup.cloud.oracle.com>; card verification only, nothing charged
on Always Free resources).

## Or: let the API do steps 1-3

`provision.py` creates the network, opens ports 22 and 80, and launches the
server with the setup script already filled in, all through Oracle's API. It
reads everything from environment variables (listed at the top of the file):
an Oracle API key from **Profile → API keys → Add API key**, plus the same
Dhan and GitHub values the script asks for.

```bash
pip install oci
python deploy/oracle/provision.py --dry-run   # check the plan
python deploy/oracle/provision.py             # create it; prints the address
```

It is safe to re-run, which matters because free Ampere servers are often
out of capacity: it tries every availability domain, and a later run picks up
where the last one stopped. Then continue at step 4.

## 1. Fill in the script

Open `deploy/oracle/cloud-init.sh` and fill in the block at the top: your Dhan
details and a GitHub token (`GH_BACKUP_TOKEN`). The token lets the new server
download your existing candle store and learning history on first boot.

## 2. Create the server

In the Oracle Cloud console: **Compute → Instances → Create instance**.

| Setting | Choose |
| --- | --- |
| Image | **Canonical Ubuntu 24.04** (or 22.04) |
| Shape | **Ampere → VM.Standard.A1.Flex**, 2 OCPUs and 12 GB is plenty (up to 4 / 24 is free) |
| Networking | Keep "Assign a public IPv4 address" on |
| SSH keys | Download the generated private key and keep it safe |
| Advanced options → Management → **Cloud-init script** | Paste the whole of `cloud-init.sh` |

Click **Create**. If you get **"Out of capacity"**, your region's free Ampere
servers are all taken right now: retry later, or try another availability
domain.

## 3. Open port 80

Oracle blocks all incoming traffic except SSH by default. On the instance page:
**Primary VNIC → Subnet → Security Lists → Default Security List → Add Ingress
Rules**:

- Source CIDR: `0.0.0.0/0`
- IP protocol: TCP
- Destination port range: `80`

The script opens the server's own firewall; this rule opens Oracle's.

## 4. Wait, then open it

Setup takes 10-15 minutes (it builds both apps). Then visit
`http://<public IP>` — the public IP is on the instance page.

To watch progress, SSH in and run:

```bash
tail -f /var/log/ati-lab-setup.log
```

## Updating later

```bash
cd /opt/ati-lab && sudo git pull \
  && sudo docker compose -f deploy/oracle/docker-compose.yml \
       --env-file deploy/oracle/.env up -d --build
```

The database lives in a Docker volume, not in the checkout, so `git pull` and
rebuilds never touch it.

## Good to know

- **Settings** (Dhan, GitHub and the rest) live in
  `/opt/ati-lab/deploy/oracle/.env` on the server. After editing it, run the
  update command above.
- **API_ACCESS_KEY** is generated on the server by the script; the web app adds
  it to every change request automatically.
- **Plain http**: the site is served over `http://` on the IP address. For
  `https://` you need a domain name pointing at the server; Caddy can then get
  a certificate by itself (replace `:80` in `Caddyfile` with the domain, and
  open port 443 as in step 3).
- **Idle reclamation**: Oracle may reclaim an Always Free server that sits
  almost completely idle for 7 days. Daily use of the app is enough to avoid it.
