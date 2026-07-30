# Frontend password lifecycle

## Route inventory

- `/signin` remains public and links to `/forgot-password`.
- `/forgot-password` is public and submits a neutral reset request.
- `/reset-password?token=...` is public and validates the reset token before rendering the reset form.
- `/settings/password` is protected for `agent` and `admin` users and changes the authenticated user password.
- `/activate` remains public. Existing admin, agent, chat, feedback, analytics, and streaming routes are unchanged.

## API client separation

Authenticated password change uses the existing authenticated Axios client, which attaches the bearer token from auth storage. Forgot-password, reset-token validation, and reset completion use a dedicated public Axios client without auth interceptors or auth-storage access. Public password-reset requests do not persist tokens, passwords, reset URLs, or request bodies.

## Secure reset-token handling

The reset page reads the `token` query parameter once, immediately removes it from visible browser history with `history.replaceState`, and keeps the token only in component memory. The token is never written to `localStorage`, `sessionStorage`, Axios defaults, logs, or analytics. A valid token is cleared after successful completion; invalid, expired, or consumed states clear it before rendering the terminal state.

## Change-own-password session behavior

After a successful authenticated password change, the page clears password fields, calls the existing auth-session clear/signout path, and redirects to `/signin?password_changed=1`. The signin page displays a non-sensitive success message asking the user to reconnect. The frontend does not expose `token_version` and does not request or store a replacement access token.

## Neutral forgot-password UX

The forgot-password page displays the backend neutral message for normal responses. It does not distinguish unknown, pending, disabled, passwordless, cooldown-suppressed, provider-failed, or eligible accounts. The submitted email is cleared after a normal response.

## Local capture testing

If the backend is explicitly configured for disposable capture mode and returns `reset_url`, the forgot-password page shows a development-only action labelled “Ouvrir le lien de test local”. The raw URL is not rendered as text, is held only in React state, and is cleared immediately before opening. Production guidance is to keep backend reset URL exposure disabled.

## Error states

Reset lifecycle codes are mapped to French states: `invalid` -> “Lien invalide”, `expired` -> “Lien expiré”, `consumed` -> “Lien déjà utilisé”, and service failures -> “Service indisponible”. Password validation errors are displayed as safe user-facing messages without backend payload dumps, stack traces, SQL errors, tokens, JWTs, or Authorization headers.

## Deferred work

Frontend reset pages are wired, but external email-provider UI, MFA, refresh tokens, device/session management, durable session controls, and IP/Redis rate-limiting interfaces remain deferred. A disposable real-browser rehearsal is still required to verify browser history, focus, autocomplete, and mobile interaction behavior outside the source/unit checks.
