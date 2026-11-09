---
name: insomnia-api-test
description: Run an authenticated API test against a BAC environment (DEV/QA) the way Insomnia does it. Use when the user asks to test/probe/call an endpoint "in Insomnia", "en insomnia", or to see what a service/client answers in an environment. Logs in through the Ping journey using the values of the user's Insomnia export, builds the request for the given environment, service path and parameters, sends it, and reports the response (plus a redacted curl to paste into Insomnia).
---

# Insomnia API Test - Usage Instructions

## Purpose

Reproduce, from the terminal, what the team does by hand in Insomnia: log in as a test user
through the Ping journey, then call a service through the environment gateway, and give the user
the real response. The user only says *what* to test (environment, service/path, parameters);
this skill does the login, builds the request and reports.

## When to use it

- "Haz pruebas en Insomnia", "prueba este endpoint en QA", "que contesta el servicio X para el
  usuario Y", "reproduce esta consulta en QA", "dame el curl para Insomnia".
- To confirm what an upstream service returns when a downstream one behaves unexpectedly
  (e.g. a score criterion that depends on another microservice).

Do not use it for load testing (use `jmeter-load-test`) or for unit/integration tests of the repo.

## Inputs

Ask for whatever is missing; never guess an endpoint, a parameter or a credential.

| Input | Required | Notes |
|---|---|---|
| Environment | yes | Name of a sub-environment in the export: `DEV`, `QA`. `PRE-PROD`/`PROD` only with explicit approval (see Guardrails). |
| Path | yes | Gateway path **including the service prefix**, e.g. `/security-devices/internal/device-metrics-information`. If the repo is available, confirm method, path, params and required headers in the controller before calling. |
| Parameters / body | depends | Query params, JSON body, extra headers. |
| Method | no | Default `GET`. Anything else needs the user's explicit confirmation. |
| Test user + password | yes | The user provides them in the conversation. They go into env vars for the run only (see Steps); never stored, never echoed. |
| Insomnia export | auto | A folder (or file) exported from Insomnia. Auto-discovered in `$INSOMNIA_EXPORT`, `~/Desktop`, `~/Downloads` (`insomnia-export*`). Ask for the path if not found. |

## Prerequisites

- Node.js 18+ (`node --version`). No npm packages needed. If Node is missing, stop and tell the
  user to install it; do not improvise another client.
- The Insomnia export must contain the environment with the login variables (`url_ping_env`,
  `realm_ping_env`, `oauth_client_id_ping`, `ping_cookie_id`, `base_url`, `publick_key_plain`,
  `private_key_plain`, `login_Api_key`, `login_helper_base_path`, `api_key`).
  `--list-envs` shows which environments are `login-ready`.
- Network access to the environment (VPN if needed).

## Steps

1. **Gather inputs** (table above). If the user said only "prueba en Insomnia", ask for
   environment, service/path and parameters.

2. **Check the endpoint in source** (optional, when the repo is the service being tested): find
   the controller to confirm path, version header (`Accept-Version`), required headers and
   params. If `graph-rag/` is installed, use `neo4j-architecture-graph` first.

3. **List environments** to validate the choice and the export:
   ```bash
   node .ai/skills/insomnia-api-test/insomnia_api_test.mjs --list-envs
   ```
   Add `--export "<path>"` if auto-discovery fails.

4. **Run the request.** Pass credentials only through environment variables of that command:
   ```bash
   # bash
   INSOMNIA_TEST_USER='<user>' INSOMNIA_TEST_PASSWORD='<password>' \
   node .ai/skills/insomnia-api-test/insomnia_api_test.mjs \
     --env QA --path /security-devices/internal/device-metrics-information \
     --query userIdentifier=<user> --print-curl
   ```
   ```powershell
   # PowerShell
   $env:INSOMNIA_TEST_USER='<user>'; $env:INSOMNIA_TEST_PASSWORD='<password>'
   node .ai/skills/insomnia-api-test/insomnia_api_test.mjs --env QA --path <path> --query k=v --print-curl
   ```
   Useful options: `--method`, `--body` / `--body-file`, `--header "K: V"`, `--accept-version`,
   `--channel`, `--country`, `--device-json`, `--fresh` (ignore cached session), `--no-cache`.
   Run `--help` for the full list.

5. **If it exits with code 3 (TAKE_OVER_REQUIRED):** the user already has an active session and
   continuing closes it (it logs the user out of their app/other device). Tell the user and
   re-run with `--take-over` **only after they agree**.

6. **Interpret and report** (reply in the user's language):
   - Environment, final URL, HTTP status, time, and the response body (JSON formatted).
   - A short reading of the result against what the user wanted to know (e.g. which field
     explains the behavior). Do not invent causes: if the body does not show it, say so.
   - The redacted curl (`--print-curl`) and where to get the secret values in Insomnia
     (`access_token`, `tokenId`, `api_key` of the chosen environment).
   - If the call failed, use the error table below before retrying.

## What the login does (reference)

The script automates the Insomnia folder "Login 2.7.x - Flujo user/pass" (the highest
`bacJourneyLogin*` version found in the export is used; override with `--journey`):

1. `POST {url_ping_env}/am/json/realms/root/realms/{realm_ping_env}/authenticate?authIndexType=service&authIndexValue=<journey>` -> `authId`.
2. Choice step: `ChoiceCallback=Login`, `publick_key_plain` and the base64 `deviceId` JSON.
3. User/password callbacks. If Ping answers `TAKE_OVER_SESSION_DECISION`, a session already exists:
   confirm with `ChoiceCallback=True` (only with `--take-over`).
4. The response carries `metadata.sessionKey` (RSA-encrypted). It is decrypted with
   `private_key_plain` (PKCS#8, RSAES-PKCS1-v1_5) and sent to `{login_helper_base_path}/helper`
   (headers `header-value`, `x-api-key: login_Api_key`) -> value used as `x-custom-session-key`.
5. The callbacks received are posted back -> `tokenId` (cookie `ping_cookie_id`).
6. `GET .../oauth2/.../authorize` (PKCE S256, `prompt=none`) -> `code`; `POST .../access_token` -> `access_token`.

Requests then carry: `Authorization: Bearer <access_token>`, `X-Custom-Token`, `x-api-key`,
`Cookie: <ping_cookie_id>=<tokenId>`, `x-device-id` (same device used at login), `traceparent`,
`channel`, `country`, `Accept-Version`, and `x-custom-session-key`.

The session (access token, tokenId, session key) is cached in the OS temp folder
(`insomnia-api-test/`, per env+user, until the token expires) so repeated calls do not log in
again - and do not close the user's session again. Use `--fresh` to force a new login.

## Known errors

| Symptom | Cause / action |
|---|---|
| Exit 3, "already has an active session" | Ask the user, then `--take-over`. |
| Exit 4 at step 3, credentials rejected | Wrong user/password or locked user. Ask the user; do not retry with variations. |
| `400 SDV_RE_00003 Required header 'traceparent'` | Header missing (the script always sends it; only appears with a custom `--header` override). |
| `404 SDV_RE_00001 Device not found for user` (security-devices) | `x-device-id` must be the device bound at login. Do not override it with a made-up value. |
| `401` / `403` from the gateway | The script discards the cached session automatically. Re-run to log in again (exit 3 means the user has another active session: ask before `--take-over`). If it still fails after a fresh login, the user lacks permission: report it. |
| `502/503/504` | The script retries a GET once. If it persists, report it as environment instability; do not loop. |
| Exit 5, "Environment ... not found / lacks login variables" | The export does not include that environment; ask the user to re-export from Insomnia. |

## Output

- Terminal output of the script (request line, status, time, response body, redacted curl).
- A summary to the user. Nothing is written to the repository.

## Guardrails

- **Credentials**: the password is only passed through `INSOMNIA_TEST_PASSWORD` for the command.
  Never put it in argv, files, commits, logs or the report; never repeat it back. Do not print
  tokens, `api_key`, `login_Api_key` or the private key; the redacted curl uses placeholders.
- **Do not copy** values from the Insomnia export into the repository.
- **Environments**: DEV and QA only by default. `PRE-PROD`/`PROD` (and anything matching
  pre/prd/prod/uat) are refused unless the user explicitly approves and `--allow-protected-env`
  is passed. Never use real customer credentials; test users only.
- **Writes**: only `GET` by default. `POST/PUT/PATCH/DELETE` change data: show the user the exact
  request first, and pass `--confirm-write` only after they approve.
- **Sessions**: a login with `--take-over` closes the user's other session. Never use it without
  telling the user. Prefer the cached session (no re-login) for follow-up calls.
- Report only what the service answered; never fabricate fields, counts or causes.
- Do not hammer the environment: no loops/retries beyond the single GET retry in the script.
