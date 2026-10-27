import { test as base, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import os from "node:os";

const root = path.resolve(import.meta.dirname, "../..");
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
const test = base.extend<{ appUrl: string }>({
  appUrl: async ({}, use) => {
    const directory = await mkdtemp(
      path.join(os.tmpdir(), "litagent-browser-"),
    );
    const sock = createServer();
    sock.listen(0, "127.0.0.1");
    await once(sock, "listening");
    const port = (sock.address() as { port: number }).port;
    await new Promise<void>((resolve) => sock.close(() => resolve()));
    const child = spawn(
      process.env.LITAGENT_PYTHON || path.join(root, ".venv/bin/python"),
      [path.join(root, "frontend/e2e/serve_fixture.py")],
      {
        cwd: root,
        env: {
          ...process.env,
          LITAGENT_QA_LOGS: directory,
          LITAGENT_QA_PORT: String(port),
        },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    let log = "";
    child.stdout.on("data", (c) => {
      log = (log + c.toString()).slice(-6000);
    });
    child.stderr.on("data", (c) => {
      log = (log + c.toString()).slice(-6000);
    });
    const appUrl = `http://127.0.0.1:${port}`;
    try {
      let ready = false;
      for (let n = 0; n < 100; n++) {
        if (child.exitCode !== null) throw Error(log);
        try {
          if ((await fetch(appUrl + "/health")).ok) {
            ready = true;
            break;
          }
        } catch {}
        await new Promise((r) => setTimeout(r, 100));
      }
      if (!ready) throw Error("Sample API did not start: " + log);
      await use(appUrl);
    } finally {
      if (child.exitCode === null) {
        child.kill("SIGTERM");
        await Promise.race([
          once(child, "exit"),
          new Promise((r) => setTimeout(r, 3000)),
        ]);
        if (child.exitCode === null) child.kill("SIGKILL");
      }
      await rm(directory, { recursive: true, force: true });
    }
  },
});

test("sample API: analyze, inspect, move, rollback and explicitly save review", async ({
  page,
  request,
  appUrl,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.goto(appUrl);
  await expect(
    page.getByRole("heading", { name: "Topics", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".paper-node")).toHaveCount(6);
  await expect(
    page.getByText("Sample mode: clusters, similarities and grades are placeholders."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Run analysis", exact: true }).click();
  // Graph 1 opens first; wait until Graph 2 has replaced it as the active version.
  await expect(
    page.getByText("Graph 2 (research gaps) is ready", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".version-selector select")).not.toHaveValue(
    "qa-root",
  );
  const analyzed = await page.locator(".version-selector select").inputValue();
  await page.getByRole("button", { name: "Graph 1 · Connections", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Connection evidence", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".inspector blockquote")).toHaveCount(2);
  const original = (
    await (await request.get(appUrl + "/cluster/qa-root")).json()
  ).output;
  expect(original.connections).toHaveLength(0);
  await page.getByRole("button", { name: "All", exact: true }).click();
  await clickMovablePaper(page, request, appUrl, analyzed);
  const target = page.getByLabel("Choose where to move");
  await expect(target.locator("option")).not.toHaveCount(1);
  const option = await target
    .locator('option:not([value=""]):not([disabled])')
    .first()
    .getAttribute("value");
  expect(option).toBeTruthy();
  await target.selectOption(option!);
  await page.getByRole("button", { name: "Preview move", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "Preview cluster changes" }),
  ).toBeVisible();
  await expect(page.locator(".change-row")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Apply as a new version", exact: true })
    .click();
  await expect(page.locator(".version-selector select")).not.toHaveValue(
    analyzed,
  );
  const moved = await page.locator(".version-selector select").inputValue();
  const changed = (
    await (await request.get(appUrl + `/cluster/${moved}`)).json()
  ).output;
  expect(changed.clusters.flatMap((c: any) => c.paper_ids).sort()).toEqual(
    original.clusters.flatMap((c: any) => c.paper_ids).sort(),
  );
  await page.getByRole("button", { name: "Versions", exact: true }).click();
  const row = page
    .locator(".version-row")
    .filter({ has: page.getByText(analyzed, { exact: true }) });
  await row.getByRole("button", { name: "Make active", exact: true }).click();
  await expect(page.locator(".version-selector select")).toHaveValue(analyzed);
  const history = (
    await (await request.get(appUrl + `/cluster/${analyzed}/versions`)).json()
  ).output;
  expect(history.active_head.run_id).toBe(analyzed);
  expect(history.versions).toHaveLength(4); // root, Graph 1, Graph 2, moved
  await page.getByRole("button", { name: "Human review", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Review items", exact: true }),
  ).toBeVisible();
  const queue = (
    await (await request.get(appUrl + `/cluster/${analyzed}/review`)).json()
  ).output.summary.total;
  expect(queue).toBeGreaterThan(0);
  await expect(page.getByText(`0 / ${queue} done`)).toBeVisible();
  // Only the verdict is required; a plain Supported keeps the finding (no rewrite).
  await page.getByRole("button", { name: "Submit", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Choose a judgement: supported, not supported or insufficient evidence.",
  );
  await page.getByLabel("Supported", { exact: true }).check();
  const quotes = page.getByRole("button", {
    name: "Quote the selection or the first passage",
    exact: true,
  });
  await quotes.nth(0).click();
  await page.getByRole("button", { name: "Submit", exact: true }).click();
  await expect(page.getByText("Submitted.")).toBeVisible();
  const review = (
    await (await request.get(appUrl + `/cluster/${analyzed}/review`)).json()
  ).output;
  expect(review.sample_mode).toBe(true);
  expect(review.summary.reviewed).toBe(1);
  expect(
    review.items.find((item: any) => item.annotation)?.annotation.reviewer,
  ).toBe("X");
  expect(review.summary.semantic_accuracy).toBeNull();
  await page.screenshot({ path: info.outputPath("review-saved.png") });
  await page.getByRole("button", { name: "Show existing grades", exact: true }).click();
  await expect(
    page.getByText('This version has no AI grades yet. Click "AI grading" to create them.'),
  ).toBeVisible();
  await page.getByRole("button", { name: "AI grading", exact: true }).click();
  await expect(
    page.getByText("Sample flow · not graded", { exact: true }),
  ).toBeVisible();
  const afterAgent = (
    await (await request.get(appUrl + `/cluster/${analyzed}/review`)).json()
  ).output;
  expect(afterAgent).toEqual(review);
  await page.getByRole("button", { name: "AI grading", exact: true }).click();
  await expect(
    page.getByText("Loaded this version's existing review; the model was not called again."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Submit", exact: true }).click();
  await expect(page.getByText("Submitted.")).toBeVisible();
  const seen = (
    await (await request.get(appUrl + `/cluster/${analyzed}/review`)).json()
  ).output;
  expect(
    seen.items.find((item: any) => item.annotation)?.annotation
      .saw_model_assessment,
  ).toBe(true);
  await page.locator(".review-item").nth(3).click();
  await expect(
    page.getByText("Needs a concrete hypothesis · not graded", { exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: info.outputPath("agent-review-sample.png") });
  await page.getByRole("button", { name: "Paper map", exact: true }).click();
  await page.getByRole("button", { name: "New map", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "New research map" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Import records", exact: true }).click();
  await dialog
    .getByRole("textbox", { name: "Research question", exact: true })
    .fill("New sample question: how do two adaptation methods compare?");
  await dialog.getByRole("button", { name: "Build map", exact: true }).click();
  await expect(page.locator(".version-selector select")).not.toHaveValue(
    analyzed,
  );
  const next = await page.locator(".version-selector select").inputValue();
  const newReview = (
    await (await request.get(appUrl + `/cluster/${next}/review`)).json()
  ).output;
  expect(newReview.summary.reviewed).toBe(0);
  await page.getByRole("button", { name: "New map", exact: true }).click();
  const importDialog = page.getByRole("dialog", { name: "New research map" });
  await importDialog
    .getByRole("button", { name: "Import records", exact: true })
    .click();
  await importDialog
    .locator('input[type="file"]')
    .setInputFiles(
      path.join(root, "input_examples/cluster-map/lora-translation.json"),
    );
  await expect(
    importDialog.getByRole("textbox", { name: "Research question", exact: true }),
  ).toHaveValue(
    "How does LoRA fine-tuning improve machine translation for low-resource languages?",
  );
  await importDialog
    .getByRole("button", { name: "Build map", exact: true })
    .click();
  await expect(page.locator(".paper-node")).toHaveCount(3);
  // Question -> search -> Human review 1 (keep/remove, feedback re-plan) -> map.
  await page.getByRole("button", { name: "New map", exact: true }).click();
  const searchDialog = page.getByRole("dialog", { name: "New research map" });
  await searchDialog
    .getByRole("textbox", { name: "Research question", exact: true })
    .fill("How do large language models handle low-resource languages?");
  await searchDialog
    .getByRole("button", { name: "Search papers", exact: true })
    .click();
  const results = searchDialog.getByRole("region", { name: "Search result review" });
  // Fast (the default mode) shows the best 50 and keeps the rest as the backup pool.
  await expect(results.getByText("Keeping 50 / 50 papers")).toBeVisible();
  await expect(results.locator(".plan-criteria")).toContainText("(default)");
  await results.getByRole("textbox").fill("Only papers since 2023");
  const replan = page.waitForRequest(
    (r) =>
      r.url().endsWith("/search") && !!r.postDataJSON().input.previous_plan,
  );
  await results.getByRole("button", { name: "Search again with feedback" }).click();
  expect((await replan).postDataJSON().input.feedback).toBe(
    "Only papers since 2023",
  );
  await expect(results.getByRole("textbox")).toHaveValue("");
  await results.getByRole("button", { name: "Deselect all" }).click();
  for (const box of (await results.getByRole("checkbox").all()).slice(0, 4))
    await box.check();
  await searchDialog
    .getByRole("button", { name: "Build the map from 4 kept papers", exact: true })
    .click();
  await expect(searchDialog).toBeHidden();
  await expect(page.locator(".paper-node")).toHaveCount(4);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("mobile: readable map, topic navigation, evidence and no horizontal overflow", async ({
  page,
  appUrl,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(appUrl);
  await expect(page.locator(".paper-node")).toHaveCount(6);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Toggle topic navigation", exact: true }).click();
  await expect(page.getByLabel("Search papers or topics")).toBeVisible();
  await page.locator(".topic-row").first().click();
  await expect(page.locator(".topic-sidebar")).not.toBeVisible();
  await page.locator(".inspector .paper-list button").first().click();
  await expect(
    page.getByRole("heading", { name: "Paper details", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".inspector blockquote")).toHaveCount(1);
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  const canvas = page.locator(".map-svg");
  await canvas.scrollIntoViewIfNeeded();
  const beforePan = await canvas
    .locator(":scope > g")
    .getAttribute("transform");
  const bounds = (await canvas.boundingBox())!;
  const touch = await page.context().newCDPSession(page);
  await touch.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [{ x: bounds.x + 25, y: bounds.y + bounds.height / 2 }],
  });
  await touch.send("Input.dispatchTouchEvent", {
    type: "touchMove",
    touchPoints: [{ x: bounds.x + 65, y: bounds.y + bounds.height / 2 + 20 }],
  });
  await touch.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await expect(canvas.locator(":scope > g")).not.toHaveAttribute(
    "transform",
    beforePan!,
  );
  await touch.detach();
  await page.getByRole("button", { name: "Show the whole map", exact: true }).click();
  await page.screenshot({
    path: info.outputPath("mobile-map.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Human review", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Review items", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("stale preview conflict is visible inside the dialog and does not move papers", async ({
  page,
  request,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole("button", { name: "Run analysis", exact: true }).click();
  // Graph 1 opens first; wait until Graph 2 has replaced it as the active version.
  await expect(
    page.getByText("Graph 2 (research gaps) is ready", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".version-selector select")).not.toHaveValue(
    "qa-root",
  );
  const id = await page.locator(".version-selector select").inputValue();
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
  expect(versions.versions).toHaveLength(3); // root, Graph 1, Graph 2
  expect(versions.active_head.run_id).toBe("qa-root");
});

test("live map while a map is built, provenance on elements, and the reasoning panel", async ({
  page,
  appUrl,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(appUrl);
  await expect(page.locator(".paper-node")).toHaveCount(6);
  // Hold the /cluster response back so the live view stays on screen; the run itself finishes on the server.
  await page.route("**/cluster", async (route) => {
    const response = await route.fetch();
    await new Promise((r) => setTimeout(r, 2500));
    await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "New map", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "New research map" });
  await dialog.getByRole("button", { name: "Import records", exact: true }).click();
  await dialog
    .locator('input[type="file"]')
    .setInputFiles(
      path.join(root, "input_examples/cluster-map/lora-translation.json"),
    );
  await dialog.getByRole("button", { name: "Build map", exact: true }).click();
  const feed = page.getByRole("complementary", { name: "Run activity" });
  await expect(feed).toBeVisible();
  await expect(feed).toContainText("Clusterer");
  await expect(page.locator(".live-build .paper-node")).toHaveCount(3);
  await expect(page.locator(".live-build")).toHaveCount(0, { timeout: 15000 });
  // B6: every element says which agent made it and why.
  await page.locator(".paper-node").first().click();
  const provenance = page.locator(".provenance");
  await expect(provenance).toContainText("Retriever");
  await expect(provenance).toContainText("Clusterer");
  // B4: the reasoning panel lists each agent's steps, labelled code or LLM, with raw details behind a toggle.
  await provenance.getByRole("button", { name: "Show reasoning" }).click();
  await expect(page.getByRole("heading", { name: "Reasoning" })).toBeVisible();
  const clusterer = page.locator(".agent-log").filter({ hasText: "Clusterer" });
  await clusterer.locator("summary").first().click();
  await expect(clusterer.locator(".kind").first()).toHaveText(/Code|LLM|Human/);
  await expect(clusterer).toContainText("assign cluster roles");
  expect(errors).toEqual([]);
});

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
