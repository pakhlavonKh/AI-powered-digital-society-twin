import { expect, test, type Page } from "@playwright/test";

// The University Simulation dashboard against its deterministic FIXTURE data source (no registry or placement API
// exists yet). One serial journey: programs -> candidates -> scenario -> results -> comparison.
test.describe.configure({ mode: "serial" });

async function heading(page: Page, name: string | RegExp) {
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

const programTable = (page: Page) => page.getByRole("table", { name: /matching program-year rows/ });

test("the sidebar opens the dashboard and the top bar labels fixture data", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Workbench" }).getByRole("link", { name: "Programs" }).click();
  await heading(page, "University & Program Explorer");
  const bar = page.getByRole("region", { name: "University data source" });
  await expect(bar.getByText("Fixture data")).toBeVisible();
  await expect(bar.getByText("Execution: fixture preview only")).toBeVisible();
  await expect(page.getByText(/^Fixture data\./)).toBeVisible();
  await page.goto("/university");
  await heading(page, "University Decision & Placement Simulator");
});

test("program filters combine, persist in the URL, reset, and open details", async ({ page }) => {
  await page.goto("/university/programs");
  await expect(programTable(page).getByRole("row")).toHaveCount(26);
  await page.getByRole("checkbox", { name: /^EA/ }).check();
  // English display label; the URL keeps the exact source value.
  await page.getByRole("checkbox", { name: /^Full scholarship/ }).check();
  await expect(page).toHaveURL(/score=EA/);
  await expect(page).toHaveURL(/scholarship=Burslu/);
  const rows = programTable(page).getByRole("row");
  await expect(rows.nth(1)).toContainText("EA");
  for (const text of await rows.allInnerTexts()) if (!text.startsWith("Code")) expect(text).toMatch(/EA[\s\S]*Full scholarship/);
  await page.reload();
  await expect(page.getByRole("checkbox", { name: /^EA/ })).toBeChecked();
  await page.getByLabel("Search university or program").fill("hukuk");
  await page.getByLabel("Search university or program").press("Enter");
  await expect(page).toHaveURL(/q=hukuk/);
  await programTable(page).getByRole("button", { name: /Open details for Hukuk/ }).first().click();
  const detail = page.getByRole("region", { name: /Hukuk ·/ });
  await expect(detail.getByRole("table", { name: /Admission history/ })).toBeVisible();
  await expect(detail.getByRole("region", { name: "Source metadata" })).toContainText("fixture:university-ui-v1");
  await expect(detail.getByRole("region", { name: "Missing fields" })).toContainText("Degree level");
  await page.getByRole("button", { name: "Reset filters" }).click();
  await expect(page.getByRole("checkbox", { name: /^EA/ })).not.toBeChecked();
  await expect(page).not.toHaveURL(/score=/);
});

test("a missing quota is shown as missing, and data quality lists warnings", async ({ page }) => {
  await page.goto("/university/programs?year=2025&q=002060101");
  const row = programTable(page).getByRole("row").nth(1);
  await expect(row).toContainText("Missing from source");
  const quality = page.getByRole("region", { name: "Data quality" });
  await expect(quality.locator(".tile").filter({ hasText: "Warnings" })).not.toContainText(/^Warnings\s*0$/);
  await quality.getByText(/Record-level findings/).click();
  await expect(quality.getByText("Missing program quota").first()).toBeVisible();
});

test("candidate details list preferences in order with the run's outcome", async ({ page }) => {
  await page.goto("/university/candidates");
  await heading(page, "Synthetic Candidate Explorer");
  await expect(page.getByLabel("Placement shown from run")).toHaveValue(/fx-/);
  await page.getByRole("radio", { name: "Placed", exact: true }).check();
  const table = page.getByRole("table", { name: /matching synthetic candidates/ });
  await expect(table.getByRole("row").nth(1)).toContainText("Placed");
  await table.getByRole("row").nth(1).getByRole("button").click();
  const prefs = page.getByRole("list", { name: "Ranked preferences" });
  await expect(prefs.getByRole("listitem").first()).toHaveAttribute("aria-label", /^Preference 1:/);
  await expect(prefs.getByText("Placed here")).toHaveCount(1);
  await expect(page.getByText("Not in schema").first()).toBeVisible();
});

test("scenario setup validates input, runs a labelled fixture preview, and links to results", async ({ page }) => {
  await page.goto("/university/scenarios");
  await heading(page, "Scenario Setup");
  await expect(page.getByRole("button", { name: /Scholarship availability change/ })).toBeDisabled();
  await page.getByLabel("Scenario name").fill("");
  await expect(page.getByRole("button", { name: "Run fixture preview" })).toBeDisabled();
  await expect(page.getByText("Enter a scenario name.").first()).toBeVisible();
  await page.getByLabel("Scenario name").fill("E2E quotas +35%");
  await page.getByRole("button", { name: /Increased program quotas/ }).click();
  await page.getByLabel("Scenario name").fill("E2E quotas +35%");
  await page.getByLabel("Program quota adjustment (%)").fill("35");
  await page.getByRole("button", { name: "Run fixture preview" }).click();
  await expect(page.getByText("Fixture preview completed")).toBeVisible();
  await expect(page.getByText(/No backend simulation ran/)).toBeVisible();
  await page.getByRole("link", { name: "View placement results" }).click();
  await heading(page, "Placement Results");
  await expect(page.getByLabel("Simulation run")).toContainText("E2E quotas +35%");
});

test("results reconcile, state the denominator and list unplaced candidates", async ({ page }) => {
  await page.goto("/university/results");
  await expect(page.getByText("Totals reconcile")).toBeVisible();
  await expect(page.getByLabel("Placement rate formula")).toContainText("placed ÷ eligible × 100");
  for (const title of ["Placement overview", "Preference ranking", "Placements by institution", "Placements by score type", "Placements by scholarship category"]) {
    await expect(page.locator(".chart-title", { hasText: title }).first()).toBeVisible();
  }
  await page.getByRole("button", { name: "Show table" }).first().click();
  await expect(page.getByRole("table", { name: /Placement overview/ })).toBeVisible();
  const unplaced = page.getByRole("region", { name: "Candidates not placed" });
  await expect(unplaced.getByRole("table")).toContainText("Every eligible preference was already full");
  await expect(page.getByRole("region", { name: "Run provenance" })).toContainText("frontend-fixture-allocator");
});

test("comparison shows pp and relative changes for compatible runs and blocks incompatible ones", async ({ page }) => {
  await page.goto("/university/compare");
  await heading(page, "Scenario Comparison");
  await expect(page.getByText("The runs are compatible")).toBeVisible();
  await expect(page.locator(".tile").filter({ hasText: "Placement rate A → B" })).toContainText(/pp · relative/);
  await expect(page.getByLabel("Comparison formulas")).toContainText("Unplaced candidate difference = B unplaced − A unplaced");
  await expect(page.getByRole("table", { name: /candidates in both runs/ })).toBeVisible();
  // A run with a different cohort seed cannot be matched candidate by candidate.
  await page.goto("/university/scenarios");
  await page.getByLabel("Scenario name").fill("E2E other cohort");
  await page.getByLabel("Cohort seed").fill("7");
  await page.getByRole("button", { name: "Run fixture preview" }).click();
  await expect(page.getByText("Fixture preview completed")).toBeVisible();
  await page.getByRole("link", { name: "Compare with another run" }).click();
  await heading(page, "Scenario Comparison");
  await expect(page.getByText("These runs cannot be compared.")).toBeVisible();
  await expect(page.getByText(/different candidate cohorts/).first()).toBeVisible();
});
