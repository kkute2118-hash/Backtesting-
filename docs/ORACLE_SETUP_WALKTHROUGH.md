# Oracle setup, step by step, assuming no prior experience

This is the click-by-click version. `docs/ORACLE_DEPLOY.md` is the short
reference for when you already know the shape of it.

Work through it in order. There are three checkpoints where you should stop
and confirm something worked before carrying on.

---

# PART A — Make an SSH key (do this first)

An SSH key is a pair of files: a **public** one you give Oracle, and a
**private** one that stays on your computer and proves you are you. Oracle's
create-instance page asks for the public one, so make the pair before you
start clicking.

**Windows:** press Start, type `PowerShell`, open it.
**Mac:** press Cmd+Space, type `Terminal`, open it.

Type this and press Enter:

```
ssh-keygen -t ed25519 -C "ati-lab"
```

It asks three questions. **Press Enter for all three** (accept the default
location, and no passphrase — a passphrase is more secure but you will be
typing it constantly).

Now print the PUBLIC key so you can copy it:

**Windows:**
```
type $env:USERPROFILE\.ssh\id_ed25519.pub
```
**Mac:**
```
cat ~/.ssh/id_ed25519.pub
```

You get one long line starting `ssh-ed25519 AAAA...` and ending `ati-lab`.
**Select it all and copy it.** You will paste it in Part B.

> The other file, `id_ed25519` with no `.pub`, is the private key. Never send
> it to anyone, never paste it into a chat, never put it in the repository.

**CHECKPOINT 1:** you have a line of text beginning `ssh-ed25519`.

---

# PART B — Create the instance

Go to https://cloud.oracle.com and sign in.

### B1. Open the create page

Click the **☰ menu** (top left) → **Compute** → **Instances** → the blue
**Create instance** button.

### B2. Name and placement

- **Name:** `ati-lab`
- **Compartment:** leave as it is
- **Placement:** leave as it is

### B3. Image and shape — the part that decides whether this is free

Find the **Image and shape** box and click **Edit**.

**Image:** click **Change image** →
- Pick **Canonical Ubuntu**
- Choose version **24.04**
- In the image list, make sure you pick the **aarch64** build (it may say
  "Ubuntu 24.04 aarch64"). Not x86_64.
- Click **Select image**

**Shape:** click **Change shape** →
- Series: **Ampere**
- Select **VM.Standard.A1.Flex**
- Set **OCPUs: 4** and **Memory: 24 GB**
- **Look for the green "Always Free-eligible" label.** If it is not there, you
  are on a shape that will cost money. Do not continue without it.
- Click **Select shape**

### B4. Networking

Scroll to **Networking**.

- Leave it on **Create new virtual cloud network** — Oracle builds the network
  for you
- Make sure **Assign a public IPv4 address** is set to **Yes**. Without this
  the machine has no internet address and you cannot reach it.

### B5. SSH keys

Scroll to **Add SSH keys**.

- Choose **Paste public keys**
- Paste the line you copied in Part A

### B6. Boot volume

Scroll to **Boot volume**.

- Leave the size at its default (around 47 GB) — that is plenty
- **Do not** turn on any backup option. Volume backups are not free.

### B7. Create

Click **Create** at the bottom.

### If it says "Out of host capacity"

**This is normal and is not your mistake.** The free ARM machines are in high
demand. Options:

- Wait a few hours and click Create again
- Try a different **Availability Domain** in the Placement section, if your
  region offers more than one
- Keep trying over a few days — people often need several attempts

**Do not switch to a different shape to get around it.** Any other shape
costs money after your 30-day credits run out. Waiting is the correct answer.

### When it works

The instance page shows **Running** in green after a minute or two. Find
**Public IP address** on that page and **write it down** — something like
`132.145.x.x`. You need it for every step below.

**CHECKPOINT 2:** instance is Running and you have its public IP.

---

# PART C — Open the web ports

Your instance can reach the internet, but the internet cannot reach it yet.

1. **☰ menu** → **Networking** → **Virtual cloud networks**
2. Click your VCN (it will have a generated name)
3. Under **Subnets**, click the **public** subnet
4. Under **Security Lists**, click the default security list
5. Click **Add Ingress Rules**, and add these two:

| | Rule 1 | Rule 2 |
|---|---|---|
| Stateless | unticked | unticked |
| Source CIDR | `0.0.0.0/0` | `0.0.0.0/0` |
| IP Protocol | TCP | TCP |
| Destination Port Range | `80` | `443` |

6. Click **Add Ingress Rules**

> `0.0.0.0/0` means "anyone on the internet", which is what a public website
> needs. Only ports 80 and 443 are opened, and only Caddy listens on them.

---

# PART D — Connect to the machine

Back in PowerShell or Terminal, using your public IP:

```
ssh ubuntu@132.145.x.x
```

First time it asks *"Are you sure you want to continue connecting?"* — type
`yes` and press Enter.

You should land on a prompt like `ubuntu@ati-lab:~$`. **You are now typing
commands on your server.**

### If it refuses

- **"Permission denied (publickey)"** — the key you pasted in B5 does not
  match the one on your computer. Re-copy it from Part A and add it under
  Instance → **Console connection**, or recreate the instance with the right
  key.
- **It hangs and times out** — usually the instance is still booting. Wait two
  minutes and retry.
- **"Bad permissions" on Mac/Linux** — run `chmod 600 ~/.ssh/id_ed25519`

**CHECKPOINT 3:** you see `ubuntu@...:~$`.

---

# PART E — Install everything

Copy and paste these two lines, one at a time, pressing Enter after each. The
second one takes about five minutes.

```
git clone https://github.com/kkute2118-hash/Backtesting-.git /tmp/ati
sudo bash /tmp/ati/deploy/oracle/bootstrap.sh
```

It prints what it is doing and finishes with a short list of what is left.
Nothing is running yet — that is intended.

---

# PART F — Your secrets

```
sudo -u ubuntu nano /etc/ati-lab/env
```

`nano` is a text editor inside the terminal. Arrow keys move the cursor; there
is no mouse.

Fill in the blanks after the `=` signs. The ones that matter:

| setting | what to put |
|---|---|
| `DHAN_CLIENT_ID` | from your Dhan account |
| `DHAN_PIN` | your Dhan PIN |
| `DHAN_TOTP_SECRET` | your Dhan TOTP secret |
| `API_ACCESS_KEY` | see below |
| `GH_BACKUP_TOKEN` | your GitHub token (same one Render uses) |
| `NEXT_PUBLIC_API_URL` | `https://132.145.x.x.nip.io` — your IP, then `.nip.io` |
| `CORS_ORIGINS` | the same value |

For `API_ACCESS_KEY`, open a **second** PowerShell/Terminal window, connect
again, and run `openssl rand -hex 32`. Copy the output. (Or use any long
random string you invent.)

To save and exit nano: **Ctrl+O**, then **Enter**, then **Ctrl+X**.

> `nip.io` is a free service that turns an IP into a hostname, which lets you
> get a proper HTTPS certificate. Certificates cannot be issued for a bare IP.
> If you buy a domain later, swap it in here and in Part G.

---

# PART G — Your web address

```
sudo cp /opt/ati-lab/deploy/oracle/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile
```

Find the line that says:

```
your-host.example.com {
```

Change it to your nip.io hostname, keeping the space and the `{`:

```
132.145.x.x.nip.io {
```

Save and exit: **Ctrl+O**, **Enter**, **Ctrl+X**.

---

# PART H — Start it

```
sudo bash /opt/ati-lab/deploy/oracle/deploy.sh
```

Takes five to ten minutes — it installs, builds the website, and pulls your
database down from the GitHub backup. At the end it prints a health check.
Everything should say `active` and `ok`.

Now open a browser and go to:

```
https://132.145.x.x.nip.io
```

Your app should load.

---

# PART I — Protect yourself from surprises

Back in the Oracle console:

1. **☰ menu** → **Billing & Cost Management** → **Budgets** → **Create Budget**
2. Set the amount to **1** and an alert at **100%**
3. Put your email in

You will not be charged on a Free Tier account — Oracle blocks rather than
bills — but this means you would hear about it immediately if anything ever
changed.

---

# Everyday commands

| what | command |
|---|---|
| Ship a code change | `sudo bash /opt/ati-lab/deploy/oracle/deploy.sh` |
| Is it running? | `systemctl status ati-lab-api ati-lab-web caddy` |
| Watch the API log | `journalctl -u ati-lab-api -f` (Ctrl+C to stop) |
| See last night's job | `journalctl -u ati-lab-daily --since yesterday` |
| When do jobs run? | `systemctl list-timers 'ati-lab-*'` |
| Run the daily job now | `sudo systemctl start ati-lab-daily` |
| Restart everything | `sudo systemctl restart ati-lab-api ati-lab-web` |

---

# Things that will go wrong, and what they mean

**The website does not load, but `systemctl status` says active.**
The firewall. `bootstrap.sh` handles it, but check:
`sudo iptables -L INPUT -n --line-numbers | head -20` — you should see ACCEPT
lines for 80 and 443. Also confirm the Part C ingress rules were saved.

**"Certificate error" in the browser.**
Caddy needs a minute to get one on first start. Check with
`journalctl -u caddy -n 50`. The usual cause is the hostname in the Caddyfile
not matching the actual IP.

**The app loads but shows no data.**
The database did not restore. Check `GH_BACKUP_TOKEN` and `GH_REPO` in
`/etc/ati-lab/env`, then re-run `deploy.sh`.

**"Dhan is not configured".**
A credential in `/etc/ati-lab/env` is wrong or missing. Edit it, then
`sudo systemctl restart ati-lab-api`.

---

# One thing not to do

**Never click "Upgrade to Pay As You Go"** in the Oracle console. That is the
only action on your account that makes a charge possible. Ignore the emails
asking you to.
