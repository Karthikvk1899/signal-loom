import { test, expect } from "@playwright/test";

test("author previews and proposes, independent reviewer activates, responsive console renders", async ({
  page,
  request,
}) => {
  const tenant = "browser-" + Date.now();
  async function credential(actor: string, role: string) {
    const response = await request.post(
      "http://localhost:8080/admin/credentials",
      {
        headers: { Authorization: "Bearer " + process.env.ADMIN_KEY },
        data: { tenant, actor, role },
      },
    );
    expect(response.status()).toBe(201);
    return (await response.json()).token;
  }
  const author = await credential("alice", "author");
  const reviewer = await credential("bob", "reviewer");
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Ship with a clear signal." }),
  ).toBeVisible();
  await page.getByLabel("Session credential").fill(author);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByRole("button", { name: "Create environment", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Propose revision" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Preview decisions" }).click();
  await expect(page.locator(".decision")).toHaveCount(3);
  await page.getByRole("button", { name: "Propose revision" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Immutable proposal created",
  );
  await page.getByRole("button", { name: "Disconnect" }).click();
  await page.getByLabel("Session credential").fill(reviewer);
  await page.getByLabel("Console view").selectOption("reviewer");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page.getByText("Inspect exact configuration").click();
  await expect(page.locator(".revision pre")).toContainText("new_checkout");
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.getByRole("button", { name: "Activate", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Release activated");
  await expect(page.locator(".audit")).toContainText("release.activated");
  await page.screenshot({
    path: "test-results/console-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Review queue" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/console-mobile.png",
    fullPage: true,
  });
});
