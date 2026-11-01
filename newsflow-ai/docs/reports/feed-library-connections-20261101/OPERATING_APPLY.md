# Operating apply — 2026-11-01

- Program commit: `2b69a0e174b514348ca02b6e3d74b658787b1c8b`.
- Applied exactly 12 files: 9 Python files and 3 built React assets. Existing operating-only settings preserved. No new POST route.
- One normal Stop (exit 0), one normal Start. Loopback port 18768; Chrome open accepted by normal launcher authentication. No browser automation or token/cookie inspection.
- 47 database tables unchanged before/after restart; current profile has 86 articles. The historical 169-article original and backup A/B are separate preserved originals, not replaced or merged.
- Private pre-apply snapshot: 417 files; 416 non-session profile files preserved, with DB contents and ACLs verified. Original/backup hashes verified. Keys were not decrypted or printed.
- No actual deletion, collection, generation API, SNS, unsigned update, main modification or PR merge.
- Automated verification: 163 distinct focused cases PASS, TypeScript/build PASS. Final operating Chrome display is for the user's manual confirmation.

## Manual check
1. News Studio → collection panel: categories are visible for public category RSS and Korean SerpApi; no collection needed.
2. Library → Images: completed TOP 3 images (or their existing review copies) have thumbnails; open the intended work/rank.
3. Photo feed → Advanced → Background image: selecting a different image refreshes the main preview/credit without Save. Same-background versions are grouped; complete older layouts remain in Saved edit version.
4. Recent generated images: per-image selection/Delete and Select delete appear. Deletion asks confirmation and moves visibility to Library Trash; originals remain recoverable. No need to confirm a real deletion to check the controls.
