import { test, expect, root } from "./fixtures";
import path from "node:path";
// Main and foundation papers are frozen (cluster roles), so pick a side paper the API says can move.
async function clickMovablePaper(
  page: import("@playwright/test").Page,
  request: import("@playwright/test").APIRequestContext,
  appUrl: string,
  runId: string,
) {
  const get = async (url: string) =>
    (await (await request.get(appUrl + url)).json()).output;
  const move = (
    await get(`/cluster/${runId}/regenerate/candidates`)
  ).candidates.find((c: any) => c.eligible);
  const title = (await get(`/cluster/${runId}/papers`)).papers.find(
    (p: any) => p.id === move.paper_id,
  ).title;
  await page
    .getByRole("button", { name: `Paper: ${title}`, exact: true })
    .click();
}
for (const mobile of [false, true]) {
  test(`analysis recovery appears only for unfinished maps (${mobile ? "mobile" : "desktop"})`, async ({
    page,
    appUrl,
  }, info) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await page.goto(appUrl);
    await expect(page).toHaveTitle("Literature Map");
    await expect(page).toHaveURL(new RegExp(appUrl));
    await expect(page.locator(".paper-node")).toHaveCount(6);
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
    await expect(
      page.locator(".app-header").getByRole("button", { name: /analysis/i }),
    ).toHaveCount(0);
    const recovery = page.getByRole("button", {
      name: "Continue analysis",
      exact: true,
    });
    await expect(recovery).toBeVisible();
    await page.screenshot({ path: info.outputPath("analysis-missing.png") });

    // Keep the first response pending to verify the recovery action disappears while work runs.
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let first = true;
    await page.route("**/analyze", async (route) => {
      const response = await route.fetch();
      if (first) {
        first = false;
        await gate;
      }
      await route.fulfill({ response });
    });
    try {
      await recovery.click();
      await expect(
        page.getByRole("complementary", { name: "Run activity" }),
      ).toContainText("Connection graph: finding connections");
      await expect(recovery).toHaveCount(0);
    } finally {
      release();
    }
    await expect(
      page.getByText("Gap graph is ready", { exact: false }),
    ).toBeVisible();
    await expect(recovery).toHaveCount(0);
    await page
      .getByRole("button", { name: "Close feedback assistant" })
      .click();
    await page.screenshot({ path: info.outputPath("analysis-complete.png") });

    // Empty findings are valid completed results; missing grades and partial findings still need recovery.
    let state: "partial" | "grades" | "empty" = "partial";
    await page.route(/\/cluster\/[^/]+$/, async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.output.status = state === "partial" ? "partial" : "done";
      body.output.analysis.completed_stages =
        state === "partial" ? ["connections"] : ["connections", "gaps"];
      body.output.analysis.pending_stages =
        state === "partial"
          ? ["gaps"]
          : state === "grades"
            ? ["connections_grade"]
            : [];
      if (state === "empty") {
        body.output.connections = [];
        body.output.gaps = [];
      }
      await route.fulfill({ response, json: body });
    });
    for (const next of ["partial", "grades", "empty"] as const) {
      state = next;
      await page.reload();
      await expect(page.locator(".paper-node")).toHaveCount(6);
      if (state === "empty") await expect(recovery).toHaveCount(0);
      else await expect(recovery).toBeVisible();
    }
    await page
      .getByRole("button", { name: "Close feedback assistant" })
      .click();
    await page
      .getByRole("button", { name: "Gap graph", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "No hypotheses have passed the checks yet",
      }),
    ).toBeVisible();
    await expect(recovery).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}

test("stale preview conflict is visible inside the dialog and does not move papers", async ({
  page,
  request,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page
    .getByRole("button", { name: "Continue analysis", exact: true })
    .click();
  // Connection graph opens first; wait until Gap graph has replaced it as the active version.
  await expect(
    page.getByText("Gap graph is ready", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Graph feedback assistant" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close feedback assistant" }).click();
  const id = new URL(page.url()).searchParams.get("run")!;
  await clickMovablePaper(page, request, appUrl, id);
  const target = page.getByLabel("Choose where to move");
  await expect(target.locator("option")).not.toHaveCount(1);
  await target.selectOption(
    (await target
      .locator('option:not([value=""]):not([disabled])')
      .first()
      .getAttribute("value"))!,
  );
  await page.getByRole("button", { name: "Preview move", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Preview cluster changes" });
  await expect(dialog).toBeVisible();
  const current = (await (await request.get(appUrl + `/cluster/${id}`)).json())
    .output;
  expect(
    (
      await request.post(appUrl + "/cluster/qa-root/activate", {
        data: {
          target_run_id: "qa-root",
          expected_head_run_id: id,
          expected_head_version_token: current.version_token,
        },
      })
    ).ok(),
  ).toBe(true);
  await dialog
    .getByRole("button", { name: "Apply as a new version", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("no longer active");
  await expect(
    dialog.getByRole("button", { name: "Apply as a new version", exact: true }),
  ).toBeDisabled();
  const versions = (
    await (await request.get(appUrl + "/cluster/qa-root/versions")).json()
  ).output;
  expect(versions.versions).toHaveLength(3); // root, Connection graph, Gap graph
  expect(versions.active_head.run_id).toBe("qa-root");
});

for (const mobile of [false, true]) {
  test(`build progress leaves paper details readable and locks unfinished views (${mobile ? "mobile" : "desktop"})`, async ({
    page,
    appUrl,
  }, info) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    const gate = () => {
      let release!: () => void;
      let started!: () => void;
      return {
        wait: new Promise<void>((resolve) => {
          release = resolve;
        }),
        started: new Promise<void>((resolve) => {
          started = resolve;
        }),
        release: () => release(),
        start: () => started(),
      };
    };
    const clustering = gate(),
      connections = gate(),
      gaps = gate();
    await page.route("**/cluster", async (route) => {
      clustering.start();
      const response = await route.fetch();
      await clustering.wait;
      await route.fulfill({ response });
    });
    await page.route("**/analyze", async (route) => {
      const stage =
        route.request().postDataJSON().stages[0] === "connections"
          ? connections
          : gaps;
      stage.start();
      const response = await route.fetch();
      await stage.wait;
      await route.fulfill({ response });
    });
    const review = page.getByRole("button", {
      name: "Human review",
      exact: true,
    });
    const reasoning = page.getByRole("button", {
      name: "Reasoning",
      exact: true,
    });
    const feed = page.getByRole("complementary", { name: "Run activity" });
    const locked = async () => {
      await expect(review).toHaveCount(0);
      await expect(
        page.getByRole("region", { name: "Graph feedback assistant" }),
      ).toHaveCount(0);
      await expect(reasoning).toBeDisabled();
      await expect(reasoning).toHaveAttribute(
        "aria-describedby",
        "workspace-navigation-status",
      );
      await expect(page.locator("#workspace-navigation-status")).toContainText(
        "available when processing finishes",
      );
      await expect(page.locator(".inspector .activity-feed")).toHaveCount(0);
    };
    try {
      await page.goto(appUrl);
      await expect(page).toHaveTitle("Literature Map");
      await expect(page).toHaveURL(new RegExp(appUrl));
      await expect(page.locator(".paper-node")).toHaveCount(6);
      await expect(reasoning).toBeEnabled();
      await page
        .getByRole("button", { name: "Create new map", exact: true })
        .click();
      const dialog = page.getByRole("dialog", { name: "New research map" });
      await dialog
        .getByRole("button", { name: "Import records", exact: true })
        .click();
      await dialog
        .locator('input[type="file"]')
        .setInputFiles(
          path.join(root, "input_examples/cluster-map/lora-translation.json"),
        );
      await dialog
        .getByRole("button", { name: "Build map", exact: true })
        .click();
      await expect(page.locator(".live-build .paper-node")).toHaveCount(3);
      await expect(page.locator(".question-bar h1")).toHaveText(
        "How does LoRA fine-tuning improve machine translation for low-resource languages?",
      );
      await locked();
      await expect(feed).toBeVisible();
      await expect(feed.locator("details")).not.toHaveAttribute("open");
      await feed.getByText("Steps", { exact: true }).click();
      await expect(feed).toContainText("Clusterer");
      await page.locator(".live-build .paper-node").first().click();
      await expect(
        page.locator(".live-build .inspector .paper-title"),
      ).toBeVisible();
      const bounds = await page.evaluate(() => ({
        feed: document
          .querySelector(".activity-feed.dock")!
          .getBoundingClientRect().bottom,
        main: document.querySelector(".workspace-grid")!.getBoundingClientRect()
          .top,
      }));
      expect(bounds.feed).toBeLessThanOrEqual(bounds.main);
      await page.screenshot({
        path: info.outputPath("build-progress.png"),
        fullPage: mobile,
      });

      clustering.release();
      await connections.started;
      await expect(page.locator(".live-build")).toHaveCount(0);
      await expect(page.locator(".paper-node")).toHaveCount(3);
      await locked();
      await expect(
        page
          .locator(".provenance")
          .getByRole("button", { name: "Show reasoning" }),
      ).toBeDisabled();
      await page.getByText("Show full abstract", { exact: true }).click();
      const abstract = page.locator(".inspector .original-text");
      await expect(abstract).toBeVisible();
      await abstract.scrollIntoViewIfNeeded();
      await expect(abstract).not.toBeEmpty();
      await expect(abstract).toBeVisible();
      await page.screenshot({
        path: info.outputPath("abstract-during-analysis.png"),
        fullPage: mobile,
      });

      connections.release();
      await gaps.started;
      await locked();
      gaps.release();
      await expect(
        page.getByText("Gap graph is ready", { exact: false }),
      ).toBeVisible();
      await expect(review).toHaveCount(0);
      await expect(
        page.getByRole("region", { name: "Graph feedback assistant" }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Close feedback assistant" })
        .click();
      await expect(reasoning).toBeEnabled();
      await expect(feed).toHaveCount(0);
      await expect(page.locator("#workspace-navigation-status")).toHaveCount(0);
      await page.locator(".paper-node").first().click();
      const provenance = page.locator(".provenance");
      await expect(provenance).toContainText("Retriever");
      await expect(provenance).toContainText("Clusterer");
      await provenance.getByRole("button", { name: "Show reasoning" }).click();
      await expect(
        page.getByRole("heading", { name: "Reasoning", exact: true }),
      ).toBeVisible();
      const clusterer = page
        .locator(".agent-log")
        .filter({ hasText: "Clusterer" });
      await clusterer.locator("summary").first().click();
      await expect(clusterer.locator(".kind").first()).toHaveText(
        /Code|LLM|Human/,
      );
      await expect(clusterer).toContainText("assign cluster roles");
      await page
        .getByRole("button", { name: "Open feedback assistant" })
        .click();
      await expect(
        page.getByRole("textbox", { name: "Feedback for the graph" }),
      ).toBeEnabled();
      await expect(page.locator("vite-error-overlay")).toHaveCount(0);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(errors).toEqual([]);
    } finally {
      clustering.release();
      connections.release();
      gaps.release();
    }
  });
}

test("each cluster shows its card: summary, years, citations and analysis depth", async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await expect(page.locator(".paper-node")).toHaveCount(6);
  await page
    .locator(".topic-list button")
    .filter({ hasText: "Main cluster" })
    .first()
    .click();
  const card = page.locator(".cluster-card");
  await expect(card).toContainText("Full-text analysis");
  await expect(card).toContainText("Sample mode: placeholder summary");
  await page
    .locator(".topic-list button")
    .filter({ hasText: "Sample side" })
    .first()
    .click();
  await expect(card).toContainText("Metadata analysis");
});

test("move preview in paper details creates a version and Versions can roll back", async ({
  page,
  request,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page
    .getByRole("button", { name: "Continue analysis", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Feedback for the graph" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Close feedback assistant" }).click();
  const source = new URL(page.url()).searchParams.get("run")!;
  await clickMovablePaper(page, request, appUrl, source);
  const target = page.getByLabel("Choose where to move");
  await expect(
    target.locator('option:not([value=""]):not([disabled])'),
  ).not.toHaveCount(0);
  await target.selectOption(
    (await target
      .locator('option:not([value=""]):not([disabled])')
      .first()
      .getAttribute("value"))!,
  );
  await page
    .locator(".inspector")
    .getByRole("button", { name: "Preview move", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Preview cluster changes" });
  await expect(dialog.locator(".change-row")).toHaveCount(2);
  await dialog
    .getByRole("button", { name: "Apply as a new version", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("run"))
    .not.toBe(source);
  await page.getByRole("button", { name: "Versions", exact: true }).click();
  const row = page
    .locator(".version-row")
    .filter({ has: page.getByText(source, { exact: true }) });
  await row.getByRole("button", { name: "Make active", exact: true }).click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("run"))
    .toBe(source);
  const history = (
    await (await request.get(appUrl + `/cluster/${source}/versions`)).json()
  ).output;
  expect(history.active_head.run_id).toBe(source);
  expect(history.versions).toHaveLength(4);
});
