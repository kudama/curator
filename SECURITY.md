# Security

Curator is an early-preview application intended for a trusted local macOS account. It binds to loopback, checks Host, uses a random HttpOnly SameSite session cookie, and requires same-origin mutation requests. It is not designed for Internet exposure, shared multi-user hosting, or reverse-proxy deployment.

Local state includes a Plex token stored without application-level encryption. State-directory and database permissions restrict access to the current account; protect that account and its backups. Executable paths are operator-controlled. Optional local analysis sends sampled media to the configured local Ollama service.

Credential-bearing Plex API and artwork requests refuse redirects. Configure the direct server root URL. Prefer HTTPS where available; HTTP sends credentials over the chosen network without transport encryption.

Do not post credentials, runtime databases, personal media, or exploitable vulnerability details in public issues. If GitHub private vulnerability reporting is enabled, use the repository Security tab to report privately. Otherwise contact the maintainer privately through an existing verified channel; a dedicated security inbox is not currently published.

Reports should include affected revision, impact, and a sanitized reproduction. No response-time or supported-version guarantee is offered during the preview.
