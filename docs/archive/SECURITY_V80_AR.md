# HR Enterprise V8.0 — Security Notes

1. Change the default administrator password immediately on first login.
2. Keep the server machine on a trusted LAN/VLAN.
3. Use Windows Firewall rules from the supplied setup script.
4. Keep backups on a second disk/network share where possible.
5. Verify restore packages before production recovery.
6. Restrict `sensitive.view`, `payroll.*`, `backup.*`, `roles.manage` and `users.manage` to trusted roles.
7. For production networks with untrusted traffic, terminate TLS at a trusted reverse proxy or provide a TLS certificate and run HTTPS.
8. Discovery uses fingerprint pinning/TOFU; if the fingerprint changes, stop and investigate instead of accepting silently.
9. Do not expose the application directly to the public Internet.
