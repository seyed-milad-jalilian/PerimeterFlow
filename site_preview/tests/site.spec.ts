import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";

const axeSourcePath = fileURLToPath(new URL("../node_modules/axe-core/axe.min.js", import.meta.url));

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};
const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; worker-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'";

function startServer() {
  return new Promise((resolve) => {
    const server = createServer(async (req, res) => {
      try {
        const url = new URL(req.url, "http://localhost");
        let pathname = decodeURIComponent(url.pathname);
        if (pathname.endsWith("/")) pathname += "index.html";
        const filePath = normalize(join(ROOT, pathname));
        if (!filePath.startsWith(normalize(ROOT))) {
          res.writeHead(403);
          res.end();
          return;
        }
        const body = await readFile(filePath);
        res.writeHead(200, {
          "Content-Type": MIME[extname(filePath)] || "application/octet-stream",
          "Content-Security-Policy": CSP,
        });
        res.end(body);
      } catch {
        res.writeHead(404, { "Content-Type": "text/plain" });
        res.end("not found");
      }
    });
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port }));
  });
}

let serverHandle;

test.beforeAll(async () => {
  const { mkdir, copyFile } = await import("node:fs/promises");
  await mkdir(join(ROOT, "test-assets"), { recursive: true });
  await copyFile(axeSourcePath, join(ROOT, "test-assets", "axe.min.js"));
  serverHandle = await startServer();
});

test.afterAll(async () => {
  if (serverHandle) await new Promise((resolve) => serverHandle.server.close(resolve));
});

async function collectCspViolations(page, url) {
  const violations = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && /Content Security Policy|Refused to (load|execute)/i.test(msg.text())) {
      violations.push(msg.text());
    }
  });
  page.on("pageerror", (err) => {
    if (/Content Security Policy|Refused to (load|execute)/i.test(err.message)) {
      violations.push(err.message);
    }
  });
  await page.goto(url, { waitUntil: "networkidle" });
  return violations;
}

test("lab page: 0 CSP violations and interactive dry-run produces live metrics", async ({ page }) => {
  const { port } = serverHandle;
  const violations = await collectCspViolations(page, `http://127.0.0.1:${port}/labs/perimeterflow/`);
  expect(violations).toEqual([]);

  await expect(page.locator("#status-badge")).toContainText("Pending Execution");
  await page.click("#lab-run");
  await expect(page.locator("#m-nrmse")).not.toHaveText("—", { timeout: 15000 });
  await expect(page.locator("#lab-disclaimer")).toContainText("Interactive Mechanics Dry-Run on Reference Sample");
  await page.click("#lens-gitops");
  await expect(page.locator("#lens-gitops-panel")).toBeVisible();
  await expect(page.locator("#lens-science-panel")).toBeHidden();
});

test("dossier: 0 CSP violations and PDF export to downloads", async ({ page }) => {
  const { port } = serverHandle;
  const violations = await collectCspViolations(page, `http://127.0.0.1:${port}/labs/perimeterflow/dossier/`);
  expect(violations).toEqual([]);

  await expect(page.locator(".sheet")).toHaveCount(4);
  const outPath = join(ROOT, "..", "downloads", "perimeterflow-technical-dossier.pdf");
  await page.pdf({
    path: outPath,
    format: "A4",
    landscape: true,
    printBackground: true,
    preferCSSPageSize: true,
  });
});

test("accessibility: 0 axe-core violations on lab and dossier pages", async ({ page }) => {
  const { port } = serverHandle;
  for (const path of ["/labs/perimeterflow/", "/labs/perimeterflow/dossier/"]) {
    await page.goto(`http://127.0.0.1:${port}${path}`, { waitUntil: "networkidle" });
    await page.addScriptTag({ url: "/test-assets/axe.min.js" });
    const results = await page.evaluate(() => window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    }));
    const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact));
    expect(serious, JSON.stringify(serious.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })))).toEqual([]);
  }
});
