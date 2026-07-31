# Demo session setup

## Prerequisites

- Odoo service running on port 8069
- [ngrok](https://ngrok.com/download) installed and authenticated

## First-time setup: claim a free static domain (one-time, manual)

ngrok's free tier includes **one static domain per account** that stays the
same every time you start the tunnel.

1. Log in at **https://dashboard.ngrok.com/domains**
2. Click **New Domain** → ngrok generates a free subdomain like
   `lucky-bear-obviously.ngrok-free.app`
3. Copy that domain name
4. Open `start-tunnel.bat` in Notepad and paste it into the `STATIC_DOMAIN=` line:
   ```
   set STATIC_DOMAIN=lucky-bear-obviously.ngrok-free.app
   ```
5. Save the file. From now on, every time you run the bat, the URL is the same.

## Start a tunnel

Double-click `start-tunnel.bat` or run it from a terminal.

- If `STATIC_DOMAIN` is set: the public URL is always the same — safe to share
  once and reuse throughout the entire test window.
- If `STATIC_DOMAIN` is blank: ngrok generates a new random URL each time.

## Stop and restart

Press **Ctrl+C** in the ngrok window. The static domain URL remains valid —
it just becomes unreachable while the tunnel is stopped. Restart the bat file
and it comes back at the same address immediately.

## Start the Odoo service (if it's not running)

Open PowerShell **as Administrator** and run:

```powershell
Start-Service -Name 'odoo-server-19.0'
```

Logs: `C:\ProgramData\Odoo\odoo-server-19.0.log`
