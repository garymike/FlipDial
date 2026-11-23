# Sign-in and the activity log

FlipDial holds personal data about other people, so anything beyond a single machine should sit behind sign-in. Pick one mode with `FLIPDIAL_AUTH_MODE`.

| Mode | Use it when |
|---|---|
| `none` | FlipDial runs on the same machine you use it from. It refuses to listen on any other address unless you also set `FLIPDIAL_ALLOW_NO_AUTH=true` (for example, a container whose port is published on `127.0.0.1` only) |
| `oidc` | You have an identity provider: Authentik, Authelia, Keycloak, Synology SSO Server, Google, Microsoft Entra, or anything else that speaks OpenID Connect |
| `proxy` | A reverse proxy already signs people in (Authelia or Authentik forward auth, oauth2-proxy) and passes the user name in a header |

## OpenID Connect

1. In your identity provider, create an application (client) for FlipDial:
   - Type: confidential (with a client secret) or public. Both work; FlipDial always uses PKCE.
   - Redirect URI: `https://<your FlipDial address>/auth/callback`
   - Scopes: `openid email profile`
2. Set these values in `.env`:

   ```sh
   FLIPDIAL_AUTH_MODE=oidc
   FLIPDIAL_PUBLIC_URL=https://flipdial.example.lan
   FLIPDIAL_OIDC_ISSUER=https://sso.example.lan/application/o/flipdial
   FLIPDIAL_OIDC_CLIENT_ID=flipdial
   FLIPDIAL_OIDC_CLIENT_SECRET=...           # leave empty for a public client
   FLIPDIAL_AUTH_ALLOWED_USERS=you@example.com
   ```

3. Restart FlipDial and open it. You are sent to your provider and back.

What FlipDial checks:

- Only people on `FLIPDIAL_AUTH_ALLOWED_USERS` get in. Entries are emails or subject IDs, separated by commas. An email counts only when the provider says it is verified. If the list is empty, nobody can sign in. Removing someone from the list ends their sessions on their next request.
- Each sign-in uses a one-time state tied to the browser that started it, a nonce, and PKCE.
- The ID token's signature (from the provider's published keys), issuer, audience, expiry and nonce must all be valid. Unsigned tokens and shared-secret signatures are refused.
- The issuer and the public address must use https. Plain http is allowed only for addresses on your local network.

Sessions:

- The browser holds only a random token, in an HttpOnly, SameSite=Lax cookie. Over https the cookie is Secure and uses the `__Host-` prefix.
- The server stores a hash of the token, never the token itself.
- A session ends after `FLIPDIAL_SESSION_IDLE_HOURS` (default 12) without use, or `FLIPDIAL_SESSION_MAX_DAYS` (default 7) after signing in, whichever comes first. **Sign out** ends it immediately.

## Reverse proxy

```sh
FLIPDIAL_AUTH_MODE=proxy
FLIPDIAL_PROXY_USER_HEADER=Remote-User
FLIPDIAL_TRUSTED_PROXIES=10.0.0.5/32        # your proxy's address
FLIPDIAL_AUTH_ALLOWED_USERS=                # optional extra allow-list
```

FlipDial trusts the header only on requests that come straight from an address in `FLIPDIAL_TRUSTED_PROXIES`. Make sure FlipDial can't be reached any other way. For example, bind it to an address only the proxy can reach.

## Activity log

**Activity log** (Wall sidebar, or the link on the Import and export screen) lists every change: edits, scans saved or dismissed, merges and undos, imports, exports, backups, syncs, and sign-ins, including refused ones. Each entry has who, what and when, and names contacts by ID only, never by their details.

The log cannot be changed from the app. The database refuses edits and deletions, and each entry includes a fingerprint (SHA-256) of the one before it. Editing an entry with other tools breaks the chain, and the integrity check at the top of the page reports where. Check from the command line with:

```sh
flipdial audit verify
```

It prints the number of entries and the latest fingerprint (`head`). Keep a note of `head` now and then: if a later check shows fewer entries or a different `head` for the same count, entries were removed from the end.

The activity log is part of the [full backup](import-export.md#full-backup).
