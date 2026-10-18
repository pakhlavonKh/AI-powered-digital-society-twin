import { expect, test, type Page } from "@playwright/test";

// The historical (v1) Ankara workbench, now under /historical, against the artificial TESTLAND fixture.
// No MatrAIx runtime and no provider keys.

async function heading(page: Page, name: string) {
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

test("historical pages stay reachable from the sidebar archive", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Workbench" }).getByRole("link", { name: /Historical/ }).click();
  await heading(page, "Historical Ankara experiment");
  for (const [path, title] of [["/historical/population", "Population Explorer"], ["/historical/cohorts", "Cohorts"], ["/historical/personas", "Persona Explorer"],
    ["/historical/experiments/new", "New Experiment"], ["/historical/results", "Results"], ["/historical/validation", "Validation"], ["/historical/data-sources", "Data Sources"]] as const) {
    await page.goto(path);
    await heading(page, title);
  }
});

test("historical overview shows backend-derived scope and recorded runs without invented metrics", async ({ page }) => {
  await page.goto("/historical");
  await expect(page.getByText("Synthetic population generated from official aggregate statistics")).toBeVisible();
  await expect(page.locator(".tile").filter({ hasText: "Synthetic residents in this build" })).toContainText("40");
  await expect(page.locator(".tile").filter({ hasText: "Geography" })).toContainText("TESTLAND");
  await expect(page.getByRole("row").filter({ hasText: "ab_complete" })).toContainText("Completed");
  await expect(page.getByRole("row").filter({ hasText: "started_only" })).toContainText("Outcome unknown");
  await expect(page.getByText("Any other province")).toBeVisible();
  await expect(page.getByText(/accuracy|success rate|budget remaining|active agents/i)).toHaveCount(0);
});

test("population filters change backend counts and live in the URL", async ({ page }) => {
  await page.goto("/historical/population");
  await expect(page.getByRole("heading", { name: "40 of 40 residents match" })).toBeVisible();
  // The checkbox is controlled by the URL, which updates asynchronously, so click and then assert.
  const female = page.getByRole("group", { name: "Sex (administrative)" }).getByLabel("female");
  await female.click();
  await expect(page).toHaveURL(/gender=female/);
  await expect(female).toBeChecked();
  const matched = page.getByRole("heading", { name: /of 40 residents match/ });
  await expect(matched).not.toHaveText("40 of 40 residents match");
  const text = (await matched.textContent()) ?? "";
  const n = Number(text.split(" ")[0]);
  await expect(page.getByRole("table").last()).toContainText(`of ${n} matching`);
  await page.getByRole("button", { name: "Reset filters" }).click();
  await expect(page.getByRole("heading", { name: "40 of 40 residents match" })).toBeVisible();
  const select = page.getByLabel("Build", { exact: true });
  const baseValue = await select.locator("option", { hasText: "base: age, sex" }).getAttribute("value");
  await select.selectOption(baseValue!);
  await expect(page.getByText("This build has no marital_status column")).toBeVisible();
});

test("a cohort is saved, reloads with the same realized IDs, and links to personas", async ({ page }) => {
  await page.goto("/historical/cohorts");
  await expect(page.getByText("Eligible residents (M)")).toBeVisible();
  await page.getByLabel("Sample size (n)").fill("3");
  await page.getByLabel("Seed").fill("5");
  await page.getByLabel("Name (optional)").fill("e2e three");
  await page.getByRole("button", { name: "Save cohort" }).click();
  await heading(page, "Cohort: e2e three");
  const ids = await page.getByRole("table", { name: /In selection order/ }).getByRole("link").allTextContents();
  expect(ids).toHaveLength(3);
  await page.reload();
  await expect(page.getByRole("table", { name: /In selection order/ }).getByRole("link")).toHaveText(ids);
  await expect(page.getByText("Source unchanged")).toBeVisible();
  await page.getByRole("link", { name: ids[0] }).click();
  await heading(page, "Persona Explorer");
  await expect(page.getByText("Source card: the population row")).toBeVisible();
});

test("persona explorer separates source cards from stored personas", async ({ page }) => {
  await page.goto("/historical/personas?record=TST2099_000001");
  await expect(page.getByText("Stored fixture persona available")).toBeVisible();
  await expect(page.getByRole("heading", { name: /MatrAIx persona YAML/ })).toBeVisible();
  await expect(page.getByText("Kept in metadata only (never shown to the model)")).toBeVisible();
  await expect(page.getByText("Line-ending drift").first()).toBeVisible();
  await expect(page.getByText("Materialization is unavailable here.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Materialize persona" })).toBeDisabled();
  await page.goto("/historical/personas?record=TST2099_000010");
  await expect(page.getByText(/Source card only/).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: /MatrAIx persona YAML/ })).toHaveCount(0);
});

test("experiment drafts save with exact blockers and cannot launch unsupported execution", async ({ page }) => {
  await page.goto("/historical/experiments/new");
  await page.getByRole("button", { name: "Step 4: Cohort" }).click();
  await page.getByLabel("Draft name").fill("e2e draft");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Saved as a draft. Execution is blocked:")).toBeVisible();
  await expect(page.getByText("model_required")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run preflight" })).toBeDisabled();
  await page.getByRole("link", { name: "Start another draft" }).click();
  await page.getByRole("button", { name: "Step 4: Cohort" }).click();
  await page.getByLabel("Model (provider/model)").fill("fakeprov/artificial-model");
  await page.getByLabel("Draft name").fill("e2e pair");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Preflight needs the external runtime, which is not available here.")).toBeVisible();
  await page.getByRole("button", { name: "Run preflight" }).click();
  await expect(page.getByText("Unavailable").first()).toBeVisible();
  await expect(page.getByText("runtime_unavailable")).toBeVisible();
});

test("results show recorded answers, labels, unknown values and the fake/live separation", async ({ page }) => {
  await page.goto("/historical/results");
  await expect(page.getByRole("table", { name: "Smoke runs" })).toContainText("smoke_fake");
  await page.getByRole("link", { name: "ab_complete" }).click();
  await expect(page.getByText("2 of 4 recorded values differ")).toBeVisible();
  await expect(page.getByText("Invented option A.").first()).toBeVisible();
  await expect(page.getByText("No label in the recorded questionnaire").first()).toBeVisible();
  const usage = page.getByRole("table", { name: "Null values are unknown, not zero" });
  await expect(usage).toContainText("(estimated)");
  await expect(usage).toContainText("unknown");
  await expect(usage).toContainText("Not recorded");
  await expect(page.getByText(/not population percentages, causal effects/)).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export JSON" }).click();
  expect((await download).suggestedFilename()).toBe("societytwin_imp_ab_complete.json");
});

test("validation keeps integrity separate from fit and invents no score", async ({ page }) => {
  await page.goto("/historical/validation");
  await expect(page.getByRole("heading", { name: "Integrity checks" })).toBeVisible();
  await expect(page.getByText("Joint age × sex TVD")).toBeVisible();
  await expect(page.getByText(/held out table comparison/i)).toBeVisible();
  await page.getByRole("link", { name: "Data sources", exact: true }).click();
  await expect(page.getByText("No datasets are registered in the root manifest.")).toBeVisible();
});


test("experiment builder keeps the scenario title while moving between design steps", async ({ page }) => {
  await page.goto("/historical/experiments/new");
  await page.getByLabel("Title", { exact: true }).fill("Local design draft");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Task", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Step 4: Cohort" }).click();
  await expect(page.getByLabel("Draft name")).toHaveValue("Local design draft");
  await page.getByRole("button", { name: "Step 1: Scenario" }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Local design draft");
});
