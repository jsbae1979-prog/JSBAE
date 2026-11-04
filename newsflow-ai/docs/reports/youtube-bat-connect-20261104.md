# YouTube BAT connection integration — 2026-11-04

The stored callback_unknown_field error predates this task (2026-10-22); current callback code already validates Google's optional iss exactly and retains state/PKCE/one-use checks. No unsupported fields were broadly accepted and old error records were not erased.

The remaining runtime defect was that the BAT local-operation boundary did not delegate YouTube connection POSTs and the generic credential cipher remains intentionally disabled. Added a dedicated connection adapter for exactly client/connect/cancel/reopen, preserving inner Windows authentication, Origin, CSRF and explicit endpoint consent. The existing service owns asynchronous callback completion and shutdown. Its current-profile client file and YouTube-only vault use the captured current-user native DPAPI factory; no global cipher setting changes. Vault use still requires the existing explicit YouTube operation context. Browser launch validates Google's HTTPS authorization endpoint and opens installed Chrome with no shell or logging. No publication/upload routes were opened.

Validation: Windows Python 3.14.7, 189 PASS / 0 FAIL / 0 ERROR; Fake provider, local callback, GUI and BAT boundary tests. New adapter tests cover exact routes, authentication delegation, wrong profile, no global credential access, encrypted config, worker completion, no duplicate request, Chrome URL validation and upload denial. Existing issuer/PKCE/callback tests reused. No real Google request or paid/SNS call during development/tests. Actual Google connection is a separate user-facing check after operating apply.

Official protocol reference: https://developers.google.com/identity/protocols/oauth2/native-app (desktop browser, loopback callback, PKCE, explicit Google consent).
