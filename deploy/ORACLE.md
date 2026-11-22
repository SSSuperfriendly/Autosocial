# Oracle Cloud Always Free VM Deployment

This guide turns AutoSocial into a normal Linux service:

- systemd keeps the app running.
- Caddy reverse proxies public HTTP/HTTPS to Uvicorn on `127.0.0.1:8000`.
- Secrets live in `/etc/autosocial/autosocial.env`.
- Persistent state lives in `/var/lib/autosocial`.
- SQLite backups run daily through a systemd timer.

## 1. Create the VM

In Oracle Cloud, create an Always Free eligible Ubuntu VM. Use Ubuntu 22.04 or 24.04 if available.

Open these inbound ports in the instance subnet security list or network security group:

- `22/tcp` for SSH.
- `80/tcp` for HTTP.
- `443/tcp` for HTTPS.

If you do not have a domain yet, the app can still run on `http://PUBLIC_IP`, but Caddy cannot issue a trusted HTTPS certificate for a bare IP address.

## 2. Copy the Project to the VM

From your local machine, copy this project to the server. Example:

```bash
scp -r AutoSocial ubuntu@YOUR_SERVER_IP:~/AutoSocial
ssh ubuntu@YOUR_SERVER_IP
cd ~/AutoSocial
```

If you later put the project in GitHub, cloning on the VM is cleaner:

```bash
git clone YOUR_REPO_URL AutoSocial
cd AutoSocial
```

## 3. Run One-Click Deployment

With a domain pointed to the VM public IP:

```bash
sudo bash deploy/scripts/deploy_oracle_ubuntu.sh --domain autosocial.example.com
```

Without a domain, use HTTP on port 80:

```bash
sudo bash deploy/scripts/deploy_oracle_ubuntu.sh --site-address :80
```

The script installs Python, Node.js 20, Caddy, creates the `autosocial` system user, builds the frontend, installs systemd units, initializes the database, and starts the service.

## 4. Configure Secrets

Edit the production environment file:

```bash
sudo nano /etc/autosocial/autosocial.env
```

Put real API keys, SMTP/IMAP credentials, sender email, and attachment directory there. Do not put secrets into Git.

Apply changes:

```bash
sudo systemctl restart autosocial
```

## 5. Operations

Check app status:

```bash
sudo systemctl status autosocial --no-pager
```

Follow logs:

```bash
sudo journalctl -u autosocial -f
```

Reload Caddy:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Run a manual backup:

```bash
sudo -u autosocial /usr/local/bin/autosocial-backup
```

Backups are written to:

```text
/var/lib/autosocial/backups
```

Check backup timer:

```bash
systemctl list-timers autosocial-backup.timer
```

## 6. Update Deployment

If the server copy is a Git checkout:

```bash
sudo /opt/autosocial/app/deploy/scripts/deploy_update.sh
```

If you copied files manually, upload the new files and rerun:

```bash
sudo bash deploy/scripts/deploy_oracle_ubuntu.sh --domain autosocial.example.com
```

The deploy script preserves existing files under `/var/lib/autosocial`.

## 7. Persistent Files

These files are kept outside the app code directory:

- `/var/lib/autosocial/data/autosocial.db`
- `/var/lib/autosocial/data/user_preferences.json`
- `/var/lib/autosocial/data/target_schools.csv`
- `/var/lib/autosocial/data/discovery_prompts.json`
- `/var/lib/autosocial/student_profile.md`
- `/var/lib/autosocial/templates`
- `/var/lib/autosocial/attachments`

The app directory uses symlinks to these persistent paths.
