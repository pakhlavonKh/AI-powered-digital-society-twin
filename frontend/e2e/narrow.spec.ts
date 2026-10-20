import { expect, test } from "@playwright/test";

test("narrow screens have no horizontal page scroll and a working menu", async ({ page }) => {
  for (const path of ["/", "/population", "/cohorts", "/personas", "/experiments/new", "/experiments", "/results", "/validation", "/data-sources", "/settings",
    "/historical", "/historical/personas?record=TST2099_000001", "/historical/results/imp_ab_complete"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${path} scrolls horizontally`).toBeLessThanOrEqual(0);
  }
  await page.goto("/");
  const menu = page.getByRole("button", { name: "Menu" });
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await menu.click();
  await page.getByRole("link", { name: "Results", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
});

test("keyboard users can skip to content", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
});
