import { test, expect } from "./fixtures";
import { blobPath } from "../src/layout";

test("cluster outlines enclose complete paper circles, including sharp corners", async ({
  page,
}) => {
  expect(blobPath([], 18)).toBe("");
  const shapes = [
    [{ x: 80, y: 90, r: 28 }],
    [
      { x: 80, y: 90, r: 28 },
      { x: 80, y: 90, r: 12 },
    ],
    [
      { x: 0, y: 0, r: 15 },
      { x: 400, y: 0, r: 26 },
    ],
    [
      { x: 0, y: 0, r: 10 },
      { x: 200, y: 0, r: 30 },
      { x: 400, y: 0, r: 12 },
    ],
    [
      { x: 0, y: 0, r: 10 },
      { x: 800, y: 0, r: 22 },
      { x: 10, y: 25, r: 14 },
    ],
    [
      { x: 0, y: 0, r: 10 },
      { x: 220, y: 0, r: 12 },
      { x: 220, y: 180, r: 20 },
      { x: 0, y: 180, r: 8 },
      { x: 40, y: 30, r: 35 },
    ],
  ];
  const failures = await page.evaluate(
    (cases) => {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      document.body.append(svg);
      const outside: string[] = [];
      cases.forEach(({ points, d }, index) => {
        const path = document.createElementNS(
          svg.namespaceURI,
          "path",
        ) as SVGPathElement;
        path.setAttribute("d", d);
        svg.append(path);
        points.forEach((p, paper) => {
          // Include the visible selection ring, not just the paper's centre.
          for (let n = 0; n < 96; n++) {
            const angle = (n * Math.PI * 2) / 96;
            if (
              !path.isPointInFill(
                new DOMPoint(
                  p.x + (p.r + 7) * Math.cos(angle),
                  p.y + (p.r + 7) * Math.sin(angle),
                ),
              )
            ) {
              outside.push(`shape ${index}, paper ${paper}, angle ${n}`);
              break;
            }
          }
        });
      });
      return outside;
    },
    shapes.map((points) => ({ points, d: blobPath(points, 18) })),
  );
  expect(failures).toEqual([]);
});

for (const mobile of [false, true]) {
  test(`finished maps keep paper nodes inside their own topics (${mobile ? "mobile" : "desktop"})`, async ({
    page,
    request,
    appUrl,
  }, info) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    const original = (
      await (await request.get(appUrl + "/cluster/qa-root")).json()
    ).output;
    // Previously saved positions can be thin or widely spread. Preserve them while repairing the outline.
    const positions = Object.fromEntries(
      original.clusters.flatMap((c: any, i: number) =>
        c.paper_ids.map((id: string, j: number) => [
          id,
          {
            x: 100 + i * 240 + (j % 2) * 180,
            y: 180 + i * 160 + (j > 1 ? 12 : 0),
          },
        ]),
      ),
    );
    await page.addInitScript(
      (saved) =>
        localStorage.setItem("litmap-layout:qa-root", JSON.stringify(saved)),
      positions,
    );
    await page.goto(appUrl);
    await expect(page).toHaveTitle("Literature Map");
    await expect(page.locator(".paper-node")).toHaveCount(6);
    await page
      .getByRole("button", { name: "Continue analysis", exact: true })
      .click();
    await expect(
      page.getByRole("button", {
        name: "Close feedback assistant",
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Close feedback assistant", exact: true })
      .click();
    const run = new URL(page.url()).searchParams.get("run");
    const map = (await (await request.get(`${appUrl}/cluster/${run}`)).json())
      .output;
    const papers = (
      await (await request.get(`${appUrl}/cluster/${run}/papers`)).json()
    ).output.papers;
    for (const filter of ["All", "Connection graph", "Gap graph"]) {
      await page.getByRole("button", { name: filter, exact: true }).click();
      await expect
        .poll(() =>
          page.evaluate(
            ({ clusters, papers }) => {
              const outside: string[] = [];
              for (const c of clusters) {
                const path = [
                  ...document.querySelectorAll<SVGPathElement>(
                    "path[aria-label]",
                  ),
                ].find(
                  (p) => p.getAttribute("aria-label") === `Topic: ${c.label}`,
                )!;
                const inverse = path.getScreenCTM()!.inverse();
                for (const id of c.paper_ids) {
                  const title = papers.find((p: any) => p.id === id).title;
                  const node = [
                    ...document.querySelectorAll<SVGGElement>(".paper-node"),
                  ].find(
                    (n) => n.getAttribute("aria-label") === `Paper: ${title}`,
                  )!;
                  const circle =
                    node.querySelector<SVGCircleElement>("circle:last-child")!;
                  const transform = circle.getScreenCTM()!;
                  const r = circle.r.baseVal.value + 7;
                  for (let n = 0; n < 64; n++) {
                    const angle = (n * Math.PI * 2) / 64;
                    const point = new DOMPoint(
                      r * Math.cos(angle),
                      r * Math.sin(angle),
                    )
                      .matrixTransform(transform)
                      .matrixTransform(inverse);
                    if (!path.isPointInFill(point)) {
                      outside.push(id);
                      break;
                    }
                  }
                }
              }
              return outside;
            },
            { clusters: map.clusters, papers },
          ),
        )
        .toEqual([]);
    }
    expect(
      await page.evaluate(() =>
        JSON.parse(localStorage.getItem("litmap-layout:qa-root")!),
      ),
    ).toEqual(positions);
    await expect(page.locator("vite-error-overlay")).toHaveCount(0);
    expect(errors).toEqual([]);
    await page.screenshot({
      path: info.outputPath("finished-cluster-boundaries.png"),
    });
  });
}
