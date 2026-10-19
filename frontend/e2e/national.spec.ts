import { expect, test, type Page } from "@playwright/test";

// The national pipeline against the ARTIFICIAL long-format package (provinces 01, 06, 69; invented values).
// One serial journey: empty states -> controls -> population -> map -> cohort -> personas -> experiment -> results.
test.describe.configure({ mode: "serial" });

async function selectByText(page: Page, label: string, text: string) {
  const select = page.getByLabel(label);
  const value = await select.locator("option", { hasText: text }).first().getAttribute("value");
  await select.selectOption(value!);
}

async function heading(page: Page, name: string | RegExp) {
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

test("sidebar groups the recorded run with experiments, and the empty dashboard reports 0 / 81 honestly", async ({ page }) => {
  await page.goto("/");
  await heading(page, "SocietyTwin Dashboard");
  const links = page.getByRole("navigation", { name: "Workbench" }).getByRole("link");
  await expect(links).toHaveText([/Dashboard/, /Population/, /Cohorts/, /Personas/, /New Experiment/, /Experiments/, /Results/, /Historical Run3/,
    /Validation/, /Data Sources/, /Settings/]);
  await expect(page.getByText("No experiment results yet.")).toBeVisible();
  await expect(page.locator(".tile").filter({ hasText: "Province coverage" })).toContainText("0 / 81");
  await expect(page.getByText(/supports all 81 provinces\. No official source data is loaded yet\./)).toBeVisible();
  await expect(page.getByRole("region", { name: "Pipeline status" }).getByRole("listitem").first()).toContainText("Not built");
});

test("empty states lead to building controls and generating a population", async ({ page }) => {
  await page.goto("/population");
  await expect(page.getByRole("heading", { name: "Control tables have not been built" })).toBeVisible();
  await page.getByRole("button", { name: "Build control tables" }).click();
  await expect(page.getByRole("heading", { name: "Population has not been generated" })).toBeVisible();
  await page.getByLabel("Synthetic records").fill("3000");
  await page.getByRole("button", { name: "Generate population" }).click();
  await heading(page, "Population Explorer");
  await expect(page.locator(".tile").filter({ hasText: "Synthetic records" })).toContainText("3,000");
  await expect(page.getByLabel("Population", { exact: true })).toContainText("3,000 records");
  await expect(page.getByText("3 of 81 provinces with source data")).toBeVisible();
});

test("the dashboard summarises real state and its map separates loaded from unloaded provinces", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".tile").filter({ hasText: "Synthetic records" })).toContainText("3,000");
  await expect(page.locator(".tile").filter({ hasText: "Province coverage" })).toContainText("3 / 81");
  await expect(page.locator(".tile").filter({ hasText: "Province coverage" })).toContainText("3 of 81 provinces loaded");
  await expect(page.getByText(/Current official source data is loaded for Adana, Ankara and Bayburt only\./)).toBeVisible();
  await expect(page.getByRole("region", { name: "Pipeline status" })).toContainText("Source data loaded: 3 / 81");
  const snapshot = page.getByRole("region", { name: "Population snapshot" });
  await expect(snapshot.getByText("Age and sex")).toBeVisible();
  await expect(snapshot.getByText("Marital status")).toBeVisible();
  const map = page.getByRole("region", { name: "Türkiye province coverage" });
  await expect(map.locator("path.prov")).toHaveCount(81);
  await expect(map.locator("a[href*='province=']")).toHaveCount(3);
  await expect(map.locator("svg").getByRole("button")).toHaveCount(78);
  await expect(map.getByText(/3 with records · 0 with source data only · 78 without source data/)).toBeVisible();
  // An unloaded province explains itself (keyboard activation) instead of opening an empty explorer.
  const izmir = map.getByRole("button", { name: /İzmir/ });
  await izmir.focus();
  await page.keyboard.press("Enter");
  await expect(izmir).toHaveAttribute("aria-pressed", "true");
  await expect(map.locator(".map-tip")).toContainText("No source data loaded");
  await expect(page).not.toHaveURL(/province=/);
  await snapshot.getByRole("link", { name: /Explore population/ }).click();
  await heading(page, "Population Explorer");
});

test("the map opens a loaded province in the explorer", async ({ page }) => {
  await page.goto("/");
  const map = page.getByRole("region", { name: "Türkiye province coverage" });
  await map.locator("a[href*='province=06']").hover();
  await expect(map.locator(".map-tip")).toContainText("Synthetic records");
  await expect(map.locator(".map-tip")).toContainText("Explore population");
  await map.locator("a[href*='province=69']").click();
  await expect(page).toHaveURL(/province=69/);
  await expect(page.locator(".tile").filter({ hasText: "Provinces" })).toContainText("Bayburt");
  await expect(page.getByText("No source table is loaded for this field in the selected provinces.").first()).toBeVisible();
});

test("filters are server-side and adults-only excludes minors", async ({ page }) => {
  await page.goto("/population");
  const records = page.locator(".tile").filter({ hasText: "Synthetic records" }).locator(".tile-value");
  await expect(records).toHaveText("3,000");
  // The checkbox mirrors the URL, which updates asynchronously: click, then assert.
  await page.getByLabel("Adults only (18+)").click();
  await expect(page).toHaveURL(/adult=1/);
  await expect(page.getByLabel("Adults only (18+)")).toBeChecked();
  await expect(records).not.toHaveText("3,000");
  await page.getByRole("link", { name: "Create cohort from this selection" }).click();
  await heading(page, "Cohorts");
  await expect(page.locator(".tile").filter({ hasText: "Minors in selection" })).toContainText("0");
});

test("a cohort is saved, sampled with a seed, and its personas show visible and hidden attributes", async ({ page }) => {
  await page.goto(`/cohorts?prefill=${encodeURIComponent(JSON.stringify({ adult_only: true }))}`);
  await page.getByLabel("Cohort name").fill("e2e adults");
  await page.getByRole("button", { name: "Save cohort" }).click();
  const card = page.locator("article").filter({ hasText: "e2e adults" });
  await expect(card).toContainText("Valid");
  await card.locator("summary", { hasText: "Draw a seeded sample" }).click();
  await card.getByRole("button", { name: "Draw sample" }).click();
  await card.getByRole("link", { name: "View personas" }).first().click();
  await heading(page, "Persona Explorer");
  await expect(page.locator(".persona-card2")).toHaveCount(20);
  await expect(page.locator(".persona-card2").first()).toContainText("Adult");
  await page.getByRole("link", { name: "View details" }).first().click();
  await expect(page.getByText("This is a fictional synthetic resident generated from aggregate statistics.")).toBeVisible();
  const visible = page.getByRole("region", { name: "Model-visible attributes" });
  await expect(visible).toContainText("Sex");
  await expect(page.getByText(/age: Hidden by default/)).toBeVisible();
});

test("the experiment builder reviews calls and cost before an explicitly confirmed stub run", async ({ page }) => {
  await page.goto("/experiments/new");
  await page.getByRole("button", { name: /Load example/ }).click();
  await expect(page.getByLabel("Scenario title")).toHaveValue("Public transport fares increase by 20%");
  await page.getByRole("button", { name: "Step 4: Cohort" }).click();
  await selectByText(page, "Saved cohort", "e2e adults");
  await page.getByRole("button", { name: "Step 6: Review" }).click();
  await page.getByRole("button", { name: "Save and review plan" }).click();
  await expect(page.locator(".tile").filter({ hasText: "Estimated calls" })).toContainText("20");
  await expect(page.locator(".tile").filter({ hasText: "Estimated cost" })).toContainText("$0");
  await expect(page.getByText(/Stub backend: deterministic placeholder/).first()).toBeVisible();
  const run = page.getByRole("button", { name: "Run experiment" });
  await expect(run).toBeDisabled();
  await page.getByRole("checkbox", { name: /I reviewed this plan/ }).check();
  await run.click();
  await expect(page).toHaveURL(/\/results\/run_/);
  await expect(page.getByText("Stub run — pipeline test only.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Response distribution (weighted)" })).toBeVisible();
  await expect(page.getByText(/valid responses from 20 personas/)).toBeVisible();
  await page.getByRole("button", { name: "Replay from cache (exact, no calls)" }).click();
  await expect(page.getByText(/replay of/)).toBeVisible();
});

test("an adult task on a cohort with minors is blocked", async ({ page }) => {
  await page.goto("/cohorts");
  await page.getByLabel("Cohort name").fill("e2e all ages");
  await page.getByRole("button", { name: "Save cohort" }).click();
  await expect(page.locator("article").filter({ hasText: "e2e all ages" })).toContainText("under 18");
  await page.goto("/experiments/new");
  await page.getByRole("button", { name: /Load example/ }).click();
  await page.getByRole("button", { name: "Step 4: Cohort" }).click();
  await selectByText(page, "Saved cohort", "e2e all ages");
  await page.getByLabel("Sample size (active personas)").fill("60");
  await page.getByRole("button", { name: "Step 5: Model" }).click();
  await page.getByLabel("Call cap (budget guard)").fill("60");
  await page.getByRole("button", { name: "Step 6: Review" }).click();
  await page.getByRole("button", { name: "Save and review plan" }).click();
  await expect(page.getByText("Execution is blocked:")).toBeVisible();
  await expect(page.getByText("minors_in_adult_task")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run experiment" })).toBeDisabled();
});

test("validation and data sources report fit, coverage and missingness without scores", async ({ page }) => {
  await page.goto("/validation");
  await expect(page.locator(".tile").filter({ hasText: "Constraint violations" })).toContainText("0");
  await expect(page.getByText("Fit by construction (calibrated)").first()).toBeVisible();
  await expect(page.getByText(/Passing it does not show that AI personas behave like real people/)).toBeVisible();
  // Artificial Bayburt (about 30 records) cannot carry its marital margin: reported, not forced.
  await expect(page.locator(".tile").filter({ hasText: "Margins not imposed" })).toContainText("1");
  await expect(page.getByText("Calibrated in some provinces only").first()).toBeVisible();
  await expect(page.getByText(/Not imposed on the weights in 1 of 3 provinces \(Bayburt \(69\)\)/)).toBeVisible();
  await page.goto("/data-sources");
  await expect(page.getByText("3/81 provinces").first()).toBeVisible();
  await expect(page.locator("summary").filter({ hasText: "ARTIFICIAL air passengers" })).toContainText("1/81 provinces");
  await expect(page.getByRole("heading", { name: "Remaining gaps" })).toBeVisible();
  await expect(page.getByText(/ARTIFICIAL air passengers: 1\/81 provinces; the others are STRUCTURALLY_UNAVAILABLE, not zero\./)).toBeVisible();
  await expect(page.getByText(/No province-level table supports/)).toContainText("labour_status");
  await expect(page.getByRole("heading", { name: "Package documentation compared with the data" })).toBeVisible();
  await expect(page.getByText(/accuracy|success rate/i)).toHaveCount(0);
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Constraint rules" })).toBeVisible();
});
