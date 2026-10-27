import { test as base, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import os from "node:os";

export const root = path.resolve(import.meta.dirname, "../..");
export const test = base.extend<{ appUrl: string; pauseFeedback: boolean }>({
  pauseFeedback: [false, { option: true }],
  appUrl: async ({ pauseFeedback }, use) => {
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
          LITAGENT_QA_PAUSE_FEEDBACK: pauseFeedback ? "1" : "0",
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
      for (let n = 0; n < 300; n++) {
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

export { expect };
