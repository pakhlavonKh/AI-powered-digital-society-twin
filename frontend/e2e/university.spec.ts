import { expect, test, type Page } from "@playwright/test";

// The University Simulation dashboard against its deterministic FIXTURE data source (no registry or placement API
// exists yet). One serial journey: programs -> candidates -> scenario -> results -> comparison.
test.describe.configure({ mode: "serial" });

async function heading(page: Page, name: string | RegExp) {
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

const programTable = (page: Page) => page.getByRole("table", { name: /matching program-year rows/ });
/** Multi-select filters are compact dropdowns: open one by its summary (labelled "<Filter>: <current value>"). */
const openMenu = (page: Page, label: string) => page.locator(`summary[aria-label^="${label}:"]`).click();

test("the sidebar opens the dashboard and the top bar labels fixture data", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Workbench" }).getByRole("link", { name: "Programs" }).click();
  await heading(page, "Programs");
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
  await expect(page.getByLabel("Program summary").locator(".tile").filter({ hasText: "Total programs" })).toContainText("76");
  await openMenu(page, "Score type");
  await page.getByRole("checkbox", { name: /^EA/ }).check();
  // English display label; the URL keeps the exact source value.
  await openMenu(page, "Scholarship");
  await page.getByRole("checkbox", { name: /^Full scholarship/ }).check();
  await expect(page).toHaveURL(/score=EA/);
  await expect(page).toHaveURL(/scholarship=Burslu/);
  const rows = programTable(page).locator("tbody tr");
  await expect(rows.first()).toContainText("EA");
  for (const text of await rows.allInnerTexts()) expect(text).toMatch(/EA[\s\S]*Full scholarship/);
  await page.reload();
  await expect(page.getByRole("button", { name: "Remove filter Score type: EA" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove filter Scholarship: Full scholarship" })).toBeVisible();
  await page.getByLabel("Search university or program").fill("hukuk");
  await page.getByLabel("Search university or program").press("Enter");
  await expect(page).toHaveURL(/q=hukuk/);
  await programTable(page).getByRole("button", { name: /^View details for Hukuk/ }).first().click();
  const detail = page.getByRole("region", { name: /Hukuk ·/ });
  await expect(detail.getByRole("table", { name: /Admission history/ })).toBeVisible();
  await expect(detail.getByRole("region", { name: "Source metadata" })).toContainText("fixture:university-ui-v1");
  await expect(detail.getByRole("region", { name: "Missing fields" })).toContainText("Degree level");
  await page.getByRole("button", { name: "Reset filters" }).click();
  await expect(page.getByRole("button", { name: /^Remove filter Score type/ })).toHaveCount(0);
  await expect(page).not.toHaveURL(/score=/);
  // Rows per page and numbered pages.
  await page.getByLabel("Rows per page").selectOption("10");
  await expect(programTable(page).locator("tbody tr")).toHaveCount(10);
  await page.getByRole("button", { name: "Page 2" }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page).toHaveURL(/size=10/);
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
  await heading(page, "Candidates");
  await expect(page.getByLabel("Simulation run")).toHaveValue(/fx-/);
  await expect(page.getByLabel("Candidate summary").locator(".tile").filter({ has: page.getByText("Placed candidates", { exact: true }) })).not.toContainText("Select a run");
  await page.getByLabel("Placement status").selectOption("placed");
  const table = page.getByRole("table", { name: /matching synthetic candidates/ });
  await expect(table.locator("tbody tr").first()).toContainText("Placed");
  await table.locator("tbody tr").first().getByRole("button", { name: /^View details/ }).click();
  const prefs = page.getByRole("table", { name: "Ranked preferences" });
  await expect(prefs.locator("tbody tr").first()).toHaveAttribute("aria-label", /^Preference 1:/);
  await expect(prefs.getByText("Placed here")).toHaveCount(1);
  await expect(page.getByRole("region", { name: "Placement outcome" })).toContainText("Placed");
  await expect(page.getByText("Not in schema").first()).toBeVisible();
  // Without a run, placement figures are unavailable rather than zero.
  await page.getByLabel("Simulation run").selectOption("");
  await expect(page.getByLabel("Candidate summary").getByText("Select a run")).toHaveCount(3);
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
