# Collection response recovery and simpler source selection — 2026-11-02

## Implemented

- News collection now offers RSS / SerpApi. RSS has a subordinate registered-source / category-news selector. Existing route identifiers and all consent/budget/local authentication controls are unchanged. Switching sources makes no collection request, and returning from SerpApi preserves the RSS choice. No new POST route was introduced.
- SerpApi accepts documented optional null metadata and source title/name variants. It strips article anchors before unchanged public-URL validation. Malformed/unsafe individual articles are excluded with fixed reason counts, while valid siblings remain available. Private, credential-bearing and file URLs remain rejected. Invalid envelopes, excessive depth/size and wholly invalid articles still stop the batch; no retries are added.
- Safe fixed-enum diagnostics survive category/global/curator handling. Supplier prose, raw response bodies, keys, headers and request URLs are not logged. Category exclusions are visible separately from date filtering; the existing 24-hour default remains unchanged.
- An expired 24-hour model authentication verification now explains expiration and directs the user to the existing API key test. Expiration is not silently extended or treated as successful verification.
- Image completion percentage is explicitly distinguished from active generation. Pending work displays “생성 시작 전 · 실행 중인 요청 없음”; uncertain results retain their separate warning and cannot be automatically resent.

## Read-only findings and limits

Stored collection #61 attempted IT/science and culture. IT/science collected/retained 98; culture failed with bad_response; the remaining categories were not requested. The original failing response was not retained, so its exact field is NOT VERIFIED. This change fixes reproduced parser defects and improves future diagnostics; it is not proof that a new culture search succeeded. Official response reference: https://serpapi.com/google-news-api . No fresh search was sent.

Claude's matching model verification was recorded on October 31 and had expired under the existing 24-hour policy. No key was changed/decrypted for this inspection and no provider verification request was made. The user must explicitly run the existing settings API key test before live analysis.

Image work #53 has completed TOP 2 and TOP 3, while TOP 1 is pending with no current generation ID. No active reserved API request was present. The displayed 66% is completion count, not evidence of generation underway. Existing images and unknown-result records were preserved.

## Verification

242 unique Python tests and 9 Node tests: **251 PASS / 0 FAIL / 0 ERROR**. Python runs: serpapi-response-final 165, serpapi-studio-final 58, serpapi-global-final 14, collection-picker-final 13. Overlapping reruns count once. tools/studio_v3/tests ran separately (58 PASS). TypeScript and React build passed; existing non-fatal bundle/font/module warnings remain.

The first parser test run had one test expectation failure: repeated failed collection tokens return the existing result view (200), not another 422. The assertion was corrected to the existing contract and verifies no new adapter call and retained failed state. Final suites above passed. Tests used Fake providers, synthetic data and isolated local Playwright. No user Chrome automation, paid calls, new collection, SNS or full-regression repeat.

## Operating application

Program source: `23c22967f1f57f97b670f6083318b2f821b6f7e9`. Nine exact program/static files were backed up and applied. Normal Stop exited 0; one Start opened Chrome through the unchanged launcher/authentication path. Current PID 41372, loopback 18768. Anonymous HTTP returned 403, preserving authentication. TCP connected and netstat attributed an established server connection to the expected PID; the CIM listener query returned no object, so no claim is based on that query.

The 47-table database and current 184 articles were unchanged. 425 non-session profile files, key/media/settings ACLs, historic 169-article originals and backup A/B were verified preserved; pre-apply snapshot has 426 files. No session tokens, DBs, keys, media or private backups are included in this report. Unrelated checkout edits remain excluded. No main/PR merge.

## Acceptance

Implementation and focused offline checks: ACCEPTED. Live supplier compatibility and user visual acceptance: CONDITIONAL / NOT VERIFIED. No actual collection, model check or image generation was retried. User can verify the two collection methods and RSS source selector in the reopened Chrome without starting collection.
