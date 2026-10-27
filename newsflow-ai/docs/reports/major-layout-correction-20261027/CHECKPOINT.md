# 재개 체크포인트

- Branch: `codex/newsflow-approved-ui-20261027`
- Base: `f88c8146dd8b79b9d020ecf02b04d7944f88abd6`
- Product SHA: `c892ba5ac3725072cd2f63ab2fcbd1b1d0a76025` / test SHA: `db616e474c16d04ca14649d9d3134beef05096b1`
- Status: CONDITIONAL. Six major layouts corrected; MINOR 4, FUNCTIONAL_CONSTRAINT 2.
- New verification: typecheck/build PASS, 56 synthetic Chrome checks PASS. Prior 88/40/17 evidence reused.
- Home 4 PNG pairs exact; non-target JSX unchanged. TOP3 text raster difference remains unexplained; matched CSS rules 50/50 identical.
- Browser major mode compares baseline CSS from the accepted f88c814 version under the local validation/major-baseline folder. Recreate that read-only test input from the accepted Git commit if running in a fresh checkout; it contains no operating data. Default existing browser mode does not require this local comparison input.
- Read MAJOR_LAYOUT_CORRECTION_REPORT.md and SCREEN_VERDICTS.json before resuming.
- No additional development, operating restart/deployment, PR35/main change, real API/SNS or packaging without user instruction.
