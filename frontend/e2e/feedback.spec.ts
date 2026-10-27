import { test, expect } from "./fixtures";

async function finish(page: import("@playwright/test").Page, appUrl: string) {
  await page.goto(appUrl);
  await expect(page).toHaveTitle("Literature Map");
  await page
    .getByRole("button", { name: "Continue analysis", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Feedback for the graph" }),
  ).toBeEnabled();
  return new URL(page.url()).searchParams.get("run")!;
}

for (const mobile of [false, true]) {
  test(`header search shows live paper and topic cards at the top (${mobile ? "mobile" : "desktop"})`, async ({
    page,
    appUrl,
  }, info) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    const paperTitle = "Efficient Adaptation for Low-Resource Languages";
    const topicTitle = "Cross-lingual Transfer Strategies";
    await page.route("**/cluster/qa-root/papers", async (route) => {
      const response = await route.fetch(),
        body = await response.json();
      body.output.papers.forEach((p: any, i: number) => {
        p.title = i === 0 ? paperTitle : `Reference Study ${i}`;
      });
      await route.fulfill({ response, json: body });
    });
    await page.route("**/cluster/qa-root", async (route) => {
      const response = await route.fetch(),
        body = await response.json();
      body.output.clusters.forEach((c: any, i: number) => {
        c.label = i === 0 ? topicTitle : `Other Topic ${i}`;
      });
      await route.fulfill({ response, json: body });
    });
    await page.goto(appUrl);
    await expect(page.locator(".paper-node")).toHaveCount(6);
    await expect(page.locator(".workspace-footer, .move-bar")).toHaveCount(0);
    await expect(page.locator(".question-bar")).not.toContainText(
      /6 papers|1 main|1 foundation/,
    );
    await expect(
      page.getByRole("button", { name: "Human review", exact: true }),
    ).toHaveCount(0);
    const create = page.getByRole("button", {
      name: "Create new map",
      exact: true,
    });
    await expect(create).toHaveCSS("color", "rgb(255, 255, 255)");
    const search = page
      .locator(".app-header")
      .getByRole("textbox", { name: "Search papers or topics" });
    const dialog = page.getByRole("region", { name: "Search results" });
    for (const query of ["adapt", "LANGUAGES adapt", "low resource"]) {
      await search.fill(query);
      await expect(dialog.locator(".search-result")).toHaveCount(1);
      await expect(dialog).toContainText(paperTitle);
      await expect(dialog.locator(".search-result")).toContainText("Paper ·");
      await dialog
        .getByRole("button", { name: "Close search results" })
        .click();
      await expect(dialog).toHaveCount(0);
    }
    await search.fill("languages adapt");
    await dialog.locator(".search-result").click();
    await expect(page.locator(".inspector .paper-title")).toHaveText(
      paperTitle,
    );
    await expect(dialog).toHaveCount(0);
    await search.fill("STRATEG transfer cross lingual");
    await expect(dialog.locator(".search-result")).toHaveCount(1);
    await expect(dialog).toContainText(topicTitle);
    await page.screenshot({ path: info.outputPath("search-results.png") });
    await dialog.locator(".search-result").click();
    await expect(page.locator(".inspector")).toContainText(topicTitle);
    await search.fill("adapt reference");
    await expect(dialog).toContainText("No matching papers or topics.");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(search).toBeFocused();
    await search.fill("reference");
    await expect(dialog.locator(".search-result")).toHaveCount(5);
    await search.press("ArrowDown");
    await expect(dialog.locator(".search-result").first()).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await search.fill("adapt");
    await expect(dialog).toBeVisible();
    const bounds = await dialog.boundingBox(),
      inputBounds = await search.boundingBox();
    expect(bounds!.y).toBeGreaterThan(inputBounds!.y);
    expect(bounds!.y - inputBounds!.y).toBeLessThan(80);
    await page.getByRole("button", { name: "Paper map", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await search.focus();
    await expect(dialog).toBeVisible();
    await page
      .getByRole("button", { name: "Clear search", exact: true })
      .click();
    await expect(search).toHaveValue("");
    await expect(dialog).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test(`feedback assistant edits a new version and can move and close (${mobile ? "mobile" : "desktop"})`, async ({
    page,
    request,
    appUrl,
  }, info) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    const source = await finish(page, appUrl);
    const bot = page.getByRole("region", { name: "Graph feedback assistant" });
    await expect(bot).toContainText("Your graph is ready");
    const handle = page.getByRole("button", {
      name: "Move feedback assistant",
    });
    const before = (await bot.boundingBox())!;
    await handle.focus();
    await handle.press("ArrowLeft");
    await handle.press("ArrowUp");
    const moved = (await bot.boundingBox())!;
    expect(moved.x).toBeLessThan(before.x);
    expect(moved.y).toBeLessThan(before.y);
    const hb = (await handle.boundingBox())!;
    await page.mouse.move(hb.x + 25, hb.y + hb.height / 2);
    await page.mouse.down();
    await page.mouse.move(hb.x + 45, hb.y + hb.height / 2 + 20, { steps: 5 });
    await page.mouse.up();
    await expect
      .poll(async () => (await bot.boundingBox())!.x)
      .toBeGreaterThan(moved.x);
    await page
      .getByRole("button", { name: "Close feedback assistant" })
      .click();
    await expect(bot).toHaveCount(0);
    await page.getByRole("button", { name: "Open feedback assistant" }).click();
    const draft = page.getByRole("textbox", { name: "Feedback for the graph" });
    await draft.fill("Separate translation methods from evaluation topics.");
    await page
      .getByRole("button", { name: "Update graph", exact: true })
      .click();
    await expect(draft).toBeEnabled();
    await expect(draft).toHaveValue("");
    await expect(bot).toContainText(
      "Separate translation methods from evaluation topics.",
    );
    await expect(bot).toContainText("a demo revision is ready");
    const next = new URL(page.url()).searchParams.get("run")!;
    expect(next).not.toBe(source);
    const get = async (suffix: string) =>
      (await (await request.get(appUrl + suffix)).json()).output;
    // The revision request returns topics and the connection graph; the gap graph is a request of its own.
    const finished = await get(`/cluster/${next}`);
    expect(finished.analysis.completed_stages).toEqual(["connections", "gaps"]);
    const revision = await get(`/cluster/${finished.parent_run_id}`);
    expect(revision.parent_run_id).toBe(source);
    expect(revision.analysis.completed_stages).toEqual(["connections"]);
    expect((await get(`/cluster/${next}/versions`)).active_head.run_id).toBe(
      next,
    );
    expect((await get(`/cluster/${source}/feedback`)).messages).toHaveLength(0);
    expect((await get(`/cluster/${next}/feedback`)).messages).toHaveLength(2);
    await page.screenshot({
      path: info.outputPath("feedback-ready.png"),
      fullPage: mobile,
    });
    await page.reload();
    await expect(bot).toContainText(
      "Separate translation methods from evaluation topics.",
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}

test("thumbs-up only saves approval, thumbs-down immediately revises; each finding has controls", async ({
  page,
  request,
  appUrl,
}) => {
  const source = await finish(page, appUrl);
  await page.getByRole("button", { name: "Close feedback assistant" }).click();
  await page.locator(".topic-row").first().click();
  let regenerated = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/feedback/regenerate")) regenerated++;
  });
  await page
    .getByRole("button", { name: "Approve this cluster", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Approve this cluster", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(regenerated).toBe(0);
  expect(new URL(page.url()).searchParams.get("run")).toBe(source);
  const stored = (
    await (await request.get(appUrl + `/cluster/${source}/feedback`)).json()
  ).output;
  expect(Object.values(stored.votes).some((v: any) => v.vote === "up")).toBe(
    true,
  );
  await page
    .getByRole("button", { name: "Connection graph", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Approve this connection", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Gap graph", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Approve this gap", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Regenerate this gap", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Feedback for the graph" }),
  ).toBeEnabled();
  expect(regenerated).toBe(1);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("run"))
    .not.toBe(source);
  await expect(
    page.getByRole("region", { name: "Graph feedback assistant" }),
  ).toContainText("I do not approve this gap");
});

test("failed feedback retains the draft and previous graph", async ({
  page,
  appUrl,
}) => {
  const source = await finish(page, appUrl);
  await page.route("**/feedback/regenerate", (route) =>
    route.fulfill({ status: 503, json: { detail: "Provider unavailable" } }),
  );
  const draft = page.getByRole("textbox", { name: "Feedback for the graph" });
  await draft.fill("Make the side topics more specific");
  await page.getByRole("button", { name: "Update graph", exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "Graph feedback assistant" })
      .getByRole("alert"),
  ).toContainText("Your feedback is still here");
  await expect(draft).toHaveValue("Make the side topics more specific");
  await expect(draft).toBeEnabled();
  expect(new URL(page.url()).searchParams.get("run")).toBe(source);
});

for (const mobile of [false, true]) {
  test(`retrieval can be cancelled without accepting late results (${mobile ? "mobile" : "desktop"})`, async ({
    page,
    appUrl,
  }, info) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(appUrl);
    await expect(page.locator(".paper-node")).toHaveCount(6);
    const original = new URL(page.url()).searchParams.get("run");
    for (const action of ["cancel", "close", "escape"]) {
      let release!: () => void, received!: () => void, finished!: () => void;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      const started = new Promise<void>((resolve) => {
        received = resolve;
      });
      const delivered = new Promise<void>((resolve) => {
        finished = resolve;
      });
      const hold = async (route: import("@playwright/test").Route) => {
        try {
          const response = await route.fetch();
          received();
          await gate;
          await route.fulfill({ response });
        } finally {
          finished();
        }
      };
      await page.route("**/search", hold);
      try {
        await page
          .getByRole("button", { name: "Create new map", exact: true })
          .click();
        const dialog = page.getByRole("dialog", { name: "New research map" });
        await dialog
          .getByRole("textbox", { name: "Research question", exact: true })
          .fill("How do language models support low-resource languages?");
        await dialog
          .getByRole("button", { name: "Search papers", exact: true })
          .click();
        await started;
        await expect(
          dialog.getByRole("button", { name: "Cancel", exact: true }),
        ).toBeEnabled();
        await expect(
          dialog.getByRole("button", { name: "Close dialog", exact: true }),
        ).toBeEnabled();
        await expect(
          dialog.getByRole("button", { name: "Searching…", exact: true }),
        ).toBeDisabled();
        if (action === "cancel")
          await page.screenshot({
            path: info.outputPath("cancel-during-retrieval.png"),
          });
        if (action === "escape") await page.keyboard.press("Escape");
        else
          await dialog
            .getByRole("button", {
              name: action === "cancel" ? "Cancel" : "Close dialog",
              exact: true,
            })
            .click();
        await expect(dialog).toHaveCount(0);
        await page
          .getByRole("button", { name: "Create new map", exact: true })
          .click();
        await expect(
          dialog.getByRole("button", { name: "Search papers", exact: true }),
        ).toBeEnabled();
        release();
        await delivered;
        await expect(
          dialog.getByRole("region", { name: "Search result review" }),
        ).toHaveCount(0);
        await expect(dialog.getByRole("alert")).toHaveCount(0);
        await dialog
          .getByRole("button", { name: "Cancel", exact: true })
          .click();
        expect(new URL(page.url()).searchParams.get("run")).toBe(original);
      } finally {
        release();
        await page.unroute("**/search", hold);
      }
    }
    await page
      .getByRole("button", { name: "Create new map", exact: true })
      .click();
    const dialog = page.getByRole("dialog", { name: "New research map" });
    await dialog
      .getByRole("textbox", { name: "Research question", exact: true })
      .fill("How do language models support low-resource languages?");
    await dialog
      .getByRole("button", { name: "Search papers", exact: true })
      .click();
    await expect(
      dialog.getByRole("region", { name: "Search result review" }),
    ).toContainText("Keeping 50 / 50 papers");
    await expect(
      dialog.getByRole("button", { name: "Cancel", exact: true }),
    ).toBeEnabled();
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

for (const mobile of [false, true]) {
  test(`provenance keeps source text readable and formats agent explanations (${mobile ? "mobile" : "desktop"})`, async ({
    page,
    appUrl,
  }, info) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    const longReason =
      "The method checks retrieved passages against the question. Its reported evaluation compares source support across several language tasks. It distinguishes supporting evidence from assumptions that still need a controlled test. "
        .repeat(5)
        .trim();
    let paperId = "";
    await page.route("**/cluster/qa-root", async (route) => {
      const response = await route.fetch(),
        body = await response.json();
      const main = body.output.clusters.find((c: any) => c.kind === "main");
      paperId = main.paper_ids[0];
      main.label = "Grounded retrieval methods";
      main.role_reason = "This topic directly addresses the research question.";
      main.rationale = `[coherent] ### Why this topic\n\n**Shared method:** the papers test grounded retrieval.\n\n- **Source support:** ${paperId} describes the method.\n- Compare the reported tasks.\n\n### Checks\n1. Keep the original evidence.\n2. Test the proposed combination.\n\nUse \`source_span\` when checking the evidence.\n\n<img src=x onerror=alert(1)>`;
      main.paper_details[0].reason = longReason;
      await route.fulfill({ response, json: body });
    });
    await page.goto(appUrl);
    await expect(page).toHaveTitle("Literature Map");
    await expect(page.locator(".paper-node")).toHaveCount(6);
    if (mobile)
      await page
        .getByRole("button", { name: "Toggle topic navigation" })
        .click();
    await page.locator(".topic-row").first().click();
    const provenance = page.locator(".provenance");
    await provenance.scrollIntoViewIfNeeded();
    const naming = provenance
      .locator(".provenance-entry")
      .filter({ has: page.locator("dt", { hasText: "Naming" }) });
    await expect(naming.locator(".provenance-status")).toHaveText("coherent");
    await expect(
      naming.getByRole("heading", { name: "Why this topic", exact: true }),
    ).toBeVisible();
    await expect(naming.locator("ul > li")).toHaveCount(2);
    await expect(naming.locator("ol > li")).toHaveCount(2);
    await expect(
      naming.locator("strong").filter({ hasText: "Shared method:" }),
    ).toBeVisible();
    await expect(naming.locator("code")).toHaveText("source_span");
    await expect(naming.locator(".paper-ref")).toHaveCount(1);
    const papers = (
      await (await page.request.get(appUrl + "/cluster/qa-root/papers")).json()
    ).output.papers;
    const paper = papers.find((p: any) => p.id === paperId);
    await expect(naming.locator(".paper-ref")).toHaveAttribute(
      "title",
      new RegExp(
        paper.title.slice(0, 20).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
      ),
    );
    await expect(naming.locator("img, script")).toHaveCount(0);
    await expect(naming).toContainText("<img src=x onerror=alert(1)>");
    expect(
      await provenance.evaluate((el) => el.scrollWidth <= el.clientWidth),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath("formatted-provenance.png"),
      fullPage: mobile,
    });
    await page.locator(".inspector .paper-list button").first().click();
    const context = provenance.locator(".provenance-context");
    await expect(context).toContainText("Assigned topic");
    await expect(context).toContainText("Grounded retrieval methods");
    await expect(context).toContainText("Question similarity");
    const explanation = provenance
      .locator(".provenance-entry")
      .last()
      .locator(".explanation-text");
    await expect(explanation.locator("p")).not.toHaveCount(1);
    expect(
      (await explanation.locator("p").allTextContents())
        .join(" ")
        .replace(/\s+/g, " ")
        .trim(),
    ).toBe(longReason);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

test.describe("saved feedback recovery", () => {
  test.use({ pauseFeedback: true });
  for (const mobile of [false, true]) {
    test(`paused feedback resumes directly without rebuilding topics (${mobile ? "mobile" : "desktop"})`, async ({
      page,
      request,
      appUrl,
    }, info) => {
      if (mobile) await page.setViewportSize({ width: 390, height: 844 });
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      const source = await finish(page, appUrl);
      let rebuilds = 0;
      page.on("request", (r) => {
        if (r.url().endsWith("/feedback/regenerate")) rebuilds++;
      });
      const bot = page.getByRole("region", {
        name: "Graph feedback assistant",
      });
      const status = bot.getByRole("region", {
        name: "Feedback update status",
      });
      await bot
        .getByRole("textbox", { name: "Feedback for the graph" })
        .fill("Make translation and evaluation separate topics.");
      await bot
        .getByRole("button", { name: "Update graph", exact: true })
        .click();
      await expect(status).toContainText("Update paused");
      await expect(status).toContainText("checking service is not configured");
      await expect(status.locator(".complete")).toContainText("Topics revised");
      await expect(bot).not.toContainText("check the status before continuing");
      await expect(bot).not.toContainText("Open the active version");
      expect(new URL(page.url()).searchParams.get("run")).toBe(source);
      const state = (
        await (await request.get(appUrl + `/cluster/${source}/feedback`)).json()
      ).output;
      const draft = state.update.run_id;
      await expect(
        status.getByRole("button", { name: "Resume update", exact: true }),
      ).toBeInViewport();
      await expect(
        status.getByRole("button", { name: "Keep current graph", exact: true }),
      ).toBeInViewport();
      await page.screenshot({ path: info.outputPath("paused-feedback.png") });
      await page.reload();
      await expect(status).toContainText("Update paused");
      await page.goto(appUrl);
      await expect
        .poll(() => new URL(page.url()).searchParams.get("run"))
        .toBe(source);
      await expect(status).toContainText("Update paused");
      await expect(bot).toContainText(
        "Make translation and evaluation separate topics.",
      );
      const stages: string[][] = [];
      page.on("request", (r) => {
        if (r.method() === "POST" && r.url().endsWith("/analyze"))
          stages.push(r.postDataJSON().stages);
      });
      const continued = page.waitForRequest(
        (r) =>
          r.method() === "POST" &&
          r.url().endsWith(`/cluster/${draft}/analyze`),
      );
      await status
        .getByRole("button", { name: "Resume update", exact: true })
        .click();
      // One request per unfinished stage, each with its own time limit
      expect((await continued).postDataJSON().stages).toEqual(["connections"]);
      await expect(
        bot.getByRole("textbox", { name: "Feedback for the graph" }),
      ).toBeEnabled();
      await expect(status).toHaveCount(0);
      await expect
        .poll(() => new URL(page.url()).searchParams.get("run"))
        .not.toBe(source);
      const next = new URL(page.url()).searchParams.get("run")!;
      const get = async (suffix: string) =>
        (await (await request.get(appUrl + suffix)).json()).output;
      const revised = await get(`/cluster/${next}`);
      expect(revised.analysis.completed_stages).toEqual([
        "connections",
        "gaps",
      ]);
      expect(
        (await get(`/cluster/${revised.parent_run_id}`)).parent_run_id,
      ).toBe(draft);
      expect(stages).toEqual([["connections"], ["gaps"]]);
      expect(rebuilds).toBe(1);
      await expect(bot).toContainText("a demo revision is ready");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(errors).toEqual([]);
    });

    test(`keep current graph after previewing a paused feedback draft (${mobile ? "mobile" : "desktop"})`, async ({
      page,
      request,
      appUrl,
    }) => {
      if (mobile) await page.setViewportSize({ width: 390, height: 844 });
      const source = await finish(page, appUrl);
      const bot = page.getByRole("region", {
        name: "Graph feedback assistant",
      });
      await bot
        .getByRole("textbox", { name: "Feedback for the graph" })
        .fill("Reconsider the topic boundaries.");
      await bot
        .getByRole("button", { name: "Update graph", exact: true })
        .click();
      const status = bot.getByRole("region", {
        name: "Feedback update status",
      });
      await expect(status).toContainText("Update paused");
      const state = (
        await (await request.get(appUrl + `/cluster/${source}/feedback`)).json()
      ).output;
      const draft = state.update.run_id;
      await status
        .getByRole("button", { name: "Preview revised topics", exact: true })
        .click();
      await expect
        .poll(() => new URL(page.url()).searchParams.get("run"))
        .toBe(draft);
      await status
        .getByRole("button", { name: "Open current graph", exact: true })
        .click();
      await expect
        .poll(() => new URL(page.url()).searchParams.get("run"))
        .toBe(source);
      await expect(status).toHaveCount(0);
      await expect(
        bot.getByRole("textbox", { name: "Feedback for the graph" }),
      ).toBeEnabled();
      await expect(bot).toContainText("Kept your current graph");
      await page.reload();
      await expect(
        bot.getByRole("textbox", { name: "Feedback for the graph" }),
      ).toBeEnabled();
      await expect(status).toHaveCount(0);
      const versions = (
        await (await request.get(appUrl + `/cluster/${source}/versions`)).json()
      ).output;
      expect(versions.active_head.run_id).toBe(source);
      expect(versions.versions.some((v: any) => v.run_id === draft)).toBe(true);
    });
  }
});
