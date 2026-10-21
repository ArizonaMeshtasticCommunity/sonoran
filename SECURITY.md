# Security policy

This file tells you how to report a security problem in Sonoran, which
versions get a fix, and what a deployment must do to be safe. It uses
ASD-STE100 Simplified Technical English.

## 1. Report a problem

Do not report a security problem in a public issue, a pull request or a
chat channel.

Use the private vulnerability reporting of this repository:

1. Open the **Security** tab of this repository on GitHub.
2. Select **Report a vulnerability**.
3. Write what you found, how to make it happen again, and what an
   attacker can get from it.

Only the maintainers can read the report. They answer in the report.

If the **Report a vulnerability** button is not there, open a public
issue that asks for a private way to report. Do not put any detail of
the problem in that issue.

Do not test against a deployment that you do not operate. A copy of the
stack on your own machine is enough to show most problems: see the
quick start in [README.md](README.md).

## 2. Supported versions

Only the latest release gets security fixes. A release is a tag named
`vYYYY.MM.DD` (see [docs/RELEASING.md](docs/RELEASING.md)). There are no
long-term branches. To get a fix, update to the latest release.

## 3. The deployment contract

**Sonoran has no authentication.** This is by design. The application
does not know who a reader is, and it does not ask. Everything the API
serves, it serves to every caller who can reach it. That includes the
positions and names of nodes and, when `STORE_TEXT_MESSAGES` is true,
the text of messages.

A deployment that other people can reach must therefore do all of
these things:

1. **Put an authenticating reverse proxy in front of it.** Examples are
   Authelia, Keycloak or oauth2-proxy behind Caddy or nginx. Do not
   publish port 8000 or 8080 on a public address. `docker-compose.yml`
   binds both to `127.0.0.1` for this reason. Keep that in your
   `docker-compose.override.yml`.
2. **Serve it over TLS only, with HSTS.** The proxy must send
   `Strict-Transport-Security` (for example
   `max-age=31536000; includeSubDomains`). Sonoran does not send it,
   because only the proxy knows that the site is served over HTTPS.
   The browser also needs HTTPS for the installed app (`docs/APP.md`)
   and for the USB config check (Web Serial).
3. **Tell uvicorn which proxy to trust.** Set `FORWARDED_ALLOW_IPS` to
   the address of the proxy, as the API container sees it. uvicorn reads
   this variable itself. It then takes the client address from
   `X-Forwarded-For` for requests from that address only. Without it,
   every caller has the address of the proxy. Behind rootless Docker,
   this is usually the gateway of the API network. Do not set it to `*`
   unless nothing but the proxy can reach the API.
4. **Turn on the request budget.** Set `API_RATE_LIMIT_ENABLED=true`
   after step 3, never before. It gives each caller a token bucket and
   answers 429 to a script that copies the database. Before step 3,
   every reader shares the proxy's address, so all readers share one
   budget. See [docs/API.md](docs/API.md) 1.1.
5. **Open only what the public needs.** If you publish the coverage
   embed without the login, open exactly the paths in
   [docs/API.md](docs/API.md) 3B.5. Never open `/api/` by prefix.

The settings in steps 3 and 4 are in [.env.example](.env.example), with
a comment on each.

## 4. What Sonoran does on its own

These do not replace the contract above.

- The JSON API has GET endpoints only.
- The API reads the database as a role with SELECT rights only.
- Each service gets only the credentials it uses (`docker-compose.yml`,
  `x-no-credentials`).
- The application containers run as a non-root user, and that user
  cannot write the application code.
- The responses carry a Content-Security-Policy and
  `X-Content-Type-Options`, and the dashboard refuses to be framed
  (`sonoran/api/app.py`).
