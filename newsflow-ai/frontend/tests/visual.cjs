"use strict";
const { chromium } = require(process.env.NEWSFLOW_PLAYWRIGHT_PACKAGE);
const fs = require("fs"),
  path = require("path"),
  assert = require("assert");
const R = process.env.NEWSFLOW_VISUAL_ROOT || __dirname,
  origin = "http://127.0.0.1:18765";
const out = path.join(R, "screenshots");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const errors = [],
    external = [],
    findings = [];
  let browser;
  try {
    const opts = {
      executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
      headless: true,
      chromiumSandbox: true,
      args: [
        "--proxy-server=http://127.0.0.1:18765",
        "--proxy-bypass-list=127.0.0.1",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
        "--disable-quic",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--disable-component-update",
      ],
    };
    browser = await chromium.launch(opts);
    for (const [width, height, dpr] of [
      [1920, 1080, 1],
      [1366, 768, 1],
      [390, 844, 1],
      [1536, 864, 1.25],
      [1280, 720, 1.5],
      [960, 540, 2],
    ]) {
      const ctx = await browser.newContext({
        viewport: { width, height },
        deviceScaleFactor: dpr,
        locale: "ko-KR",
        acceptDownloads: false,
        serviceWorkers: "block",
      });
      await ctx.route("**/*", (route) => {
        const u = new URL(route.request().url());
        if (u.origin !== origin) {
          external.push(u.origin);
          return route.abort();
        }
        return route.continue();
      });
      const page = await ctx.newPage();
      page.on("pageerror", (e) => errors.push(String(e)));
      page.on("console", (m) => {
        if (m.type() === "error") errors.push(m.text());
      });
      for (const name of ["dashboard", "create"]) {
        assert.equal(
          (
            await page.goto(origin + "/studio/" + name, {
              waitUntil: "networkidle",
            })
          ).status(),
          200,
        );
        await page.evaluate(() => document.fonts.ready);
        await page.waitForTimeout(150);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth + 1,
        );
        assert.equal(overflow, false, `horizontal overflow ${name} ${width}`);
        assert(await page.getByRole("heading", { level: 1 }).isVisible());
        await page.screenshot({
          path: path.join(out, `${name}-${width}x${height}-dpr${dpr}.png`),
          fullPage: true,
          animations: "disabled",
        });
        findings.push({ page: name, width, height, dpr, overflow: false });
      }
      await ctx.close();
    }
    const ctx = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      acceptDownloads: false,
      serviceWorkers: "block",
    });
    await ctx.route("**/*", (r) =>
      new URL(r.request().url()).origin === origin ? r.continue() : r.abort(),
    );
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(origin + "/studio/dashboard");
    await page.getByRole("button", { name: "새 프로젝트 시작하기" }).click();
    await page
      .getByRole("heading", { name: "어떤 콘텐츠를 만들까요?" })
      .waitFor();
    await page.getByRole("button", { name: "이미지", exact: true }).click();
    assert.equal(await page.locator(".project").count(), 2);
    await page.getByRole("button", { name: "목록 보기" }).click();
    assert(await page.locator(".projects.list").isVisible());
    await page
      .getByRole("searchbox")
      .count()
      .catch(() => 0);
    const search = page.getByRole("textbox", { name: "보관 프로젝트 검색" });
    await search.fill("존재하지않는합성제목");
    await page.getByText("검색 결과가 없습니다", { exact: true }).waitFor();
    await search.fill("");
    await page.getByRole("button", { name: "전체", exact: true }).click();
    assert.equal(await page.locator(".project").count(), 4);
    await page
      .getByRole("button", { name: /이미지 한 장/ })
      .count()
      .catch(() => 0);
    await page.locator(".quick-card.image").click();
    await page.getByRole("dialog").waitFor();
    assert(
      await page
        .getByRole("button", { name: "AI 이미지 생성", exact: true })
        .isVisible(),
    );
    assert(
      await page
        .getByRole("button", { name: "뉴스 이미지 게시물", exact: true })
        .isVisible(),
    );
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("dialog").isVisible(), false);
    await page.locator(".project").filter({ hasText: "새로운 기술" }).click();
    await page
      .getByRole("dialog")
      .getByText("결과 불명", { exact: true })
      .waitFor();
    assert.equal(await page.locator("video").count(), 0);
    await page.getByRole("button", { name: "닫기", exact: true }).click();
    await page.getByRole("button", { name: "메뉴 접기", exact: true }).click();
    assert(await page.locator(".app.collapsed").count());
    await page
      .getByRole("button", { name: "메뉴 펼치기", exact: true })
      .click();
    await page.reload();
    await page
      .getByRole("heading", { name: "어떤 콘텐츠를 만들까요?" })
      .waitFor();
    await page.getByRole("button", { name: "홈", exact: true }).click();
    await page.getByRole("heading", { name: /뉴스가 세상을/ }).waitFor();
    await page
      .getByRole("button", { name: "뉴스 스튜디오", exact: true })
      .click();
    await page
      .getByRole("button", { name: "기존 뉴스 스튜디오 열기" })
      .waitFor();
    assert(
      await page
        .getByRole("button", { name: "기존 뉴스 스튜디오 열기" })
        .isDisabled(),
    );
    await page.keyboard.press("Escape");
    await page.keyboard.press("Control+k");
    assert.equal(
      await search.evaluate((e) => e === document.activeElement),
      true,
    );
    const empty = {
      schemaVersion: 1,
      dataOrigin: "local-workspace",
      projects: [],
      stats: { running: 0, ready: 0, publishDrafts: 0, total: 0 },
      today: {
        done: 0,
        running: 0,
        waiting: 0,
        failed: 0,
        unknown: 0,
        total: 0,
      },
      services: [],
      upcoming: [],
      upcomingStatus: "connected",
      activity: [],
    };
    await page.route("**/api/studio/workspace", (r) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(empty),
      }),
    );
    await page.reload();
    await page
      .getByText("아직 제작한 프로젝트가 없습니다", { exact: true })
      .waitFor();
    assert.equal(await page.locator(".dev-badge").count(), 0);
    assert.equal(await page.locator(".project").count(), 0);
    await page.screenshot({
      path: path.join(out, "dashboard-empty-1920.png"),
      fullPage: true,
    });
    await page.unroute("**/api/studio/workspace");
    await page.route("**/api/studio/workspace", (r) =>
      r.fulfill({ status: 503, contentType: "application/json", body: "{}" }),
    );
    await page.reload();
    await page.getByRole("alert").waitFor();
    assert.equal(await page.locator(".project").count(), 0);
    await page.screenshot({
      path: path.join(out, "dashboard-error-1920.png"),
      fullPage: true,
    });
    await page.unroute("**/api/studio/workspace");
    await page.getByRole("button", { name: "다시 불러오기" }).click();
    await page.locator(".project").first().waitFor();
    await page.goto(origin + "/studio/create");
    await page.getByRole("button", { name: "이미지", exact: true }).click();
    await page.locator(".project").filter({ hasText: "새로운 기술" }).click();
    assert.equal(await page.locator("video").count(), 0);
    await page.keyboard.press("Escape");
    assert.equal(errors.length, 0, JSON.stringify(errors));
    assert.equal(external.length, 0, JSON.stringify(external));
    await ctx.close();
    fs.writeFileSync(
      path.join(R, "visual-results-safe.json"),
      JSON.stringify(
        {
          PASS: true,
          captures: findings,
          interactions: [
            "creation navigation",
            "type filtering",
            "local title search and empty state",
            "grid/list",
            "distinct image workflows",
            "unknown no playback",
            "dialog Escape and close",
            "sidebar toggle",
            "deep reload",
            "legacy bridge",
            "keyboard search",
            "empty production state",
            "error state",
            "manual reload",
          ],
          JavaScript_errors: errors,
          external_page_requests: external,
          OS_DPI: "NOT VERIFIED; browser viewport/device-scale emulation only",
          backend_engine: "NOT VERIFIED; visual fixtures only",
        },
        null,
        2,
      ),
    );
    console.log(
      JSON.stringify({
        PASS: true,
        captures: findings.length,
        interactions: 14,
        errors: 0,
        external_page_requests: 0,
      }),
    );
  } finally {
    if (browser) await browser.close();
  }
})().catch((e) => {
  console.error(String(e));
  process.exitCode = 1;
});
