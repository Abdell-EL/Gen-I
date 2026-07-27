# Backend authentication contract

The frontend currently defaults to `VITE_AUTH_MODE=demo` so the product flows can
be previewed before backend authentication exists. Demo mode stores users,
credentials and tokens in `localStorage`. It is not production security.

Production deployment must use `VITE_AUTH_MODE=backend` and implement the
endpoints below under `/api/v1/auth`.

## User and session types

```ts
type AuthUser = {
  id: number | string;
  name: string;
  email: string;
  role: "agent" | "admin";
};

type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
};
```

## `POST /api/v1/auth/signin`

Request:

```json
{
  "email": "agent@example.com",
  "password": "user-password"
}
```

Success response: `200 AuthResponse`.

Recommended failures:

- `401` for invalid credentials.
- `403` for a disabled or unauthorized account.
- `422` for invalid input.

## `POST /api/v1/auth/signup`

Request:

```json
{
  "name": "User Name",
  "email": "user@example.com",
  "password": "user-password",
  "role": "agent"
}
```

Success response: `201 AuthResponse`.

In production, public self-registration as `admin` should not be accepted
without an invitation or approval workflow. The backend is authoritative and
may downgrade or reject a requested role.

## `GET /api/v1/auth/me`

Requires `Authorization: Bearer <access_token>`.

Success response: `200 AuthUser`.

Return `401` when the token is missing, invalid or expired.

## `POST /api/v1/auth/logout`

Requires `Authorization: Bearer <access_token>`.

Recommended response: `204 No Content`. The backend should revoke the active
session or refresh token where applicable.

## Authorization rules

- `/agent` data and chat operations require an authenticated `agent` or
  `admin`.
- `/admin`, health, stats and audit administration require `admin`.
- Backend routes must enforce these rules. React route guards only improve
  navigation and cannot provide security.
- Existing chat and retrieval audit logging should use the authenticated user
  instead of the current development user.
- Passwords must be hashed server-side. Never store plain-text credentials.
- CORS must allow the deployed frontend origin and the `Authorization` header.
- Token expiration and refresh behavior should be defined before production.
