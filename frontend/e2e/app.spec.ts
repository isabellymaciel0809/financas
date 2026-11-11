import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

// Teste de ponta a ponta: navegador de verdade, frontend e API rodando, banco novo e temporário.
// Os testes rodam em ordem: o primeiro cria a conta que os outros usam.
test.describe.configure({ mode: "serial" });

const USER = "teste-e2e";
const PASSWORD = "senha-do-teste-e2e";
const NOTA = fileURLToPath(new URL("./fixtures/nota-exemplo.xml", import.meta.url));

async function entrar(page: Page, password = PASSWORD) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Entrar" })).toBeVisible();
  await page.getByLabel("Usuário").fill(USER);
  await page.getByLabel("Senha").fill(password);
  await page.getByRole("button", { name: "Entrar" }).click();
}

test("primeiro acesso: cria a conta e lança uma nota fiscal pelo XML", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Criar a primeira conta" })).toBeVisible();
  await page.getByLabel("Usuário").fill(USER);
  await page.getByLabel(/^Senha/).fill(PASSWORD);
  await page.getByLabel("Repita a senha").fill(PASSWORD);
  await page.getByRole("button", { name: "Criar conta e entrar" }).click();

  // Entrou: a primeira tela é a de lançamentos da empresa.
  await expect(page.getByRole("button", { name: USER })).toBeVisible();
  await expect(page.getByText("Enviar notas e cupons")).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles(NOTA);

  // A leitura roda em segundo plano; a lista atualiza sozinha até sair de "Processando".
  const linha = page.getByRole("row").filter({ hasText: "FRIGELAR" });
  await expect(linha).toBeVisible({ timeout: 30_000 });
  await expect(linha).toContainText("Confirmado", { timeout: 30_000 });
  await expect(linha).toContainText("68,30");
});

test("visão geral: dados de exemplo mostram o alerta de gasto fora do padrão", async ({ page }) => {
  await entrar(page);
  await page.getByRole("button", { name: "Visão geral" }).click();
  await page.getByRole("button", { name: "Usar dados de exemplo" }).click();

  const alertas = page.getByRole("region", { name: "Gastos fora do padrão" });
  await expect(alertas).toBeVisible();
  await expect(alertas).toContainText("Compras");
  await expect(alertas).toContainText("acima da média");
  await expect(page.getByText("Categorizado automaticamente")).toBeVisible();
});

test("extrato: lançamento por texto mostra a prévia e só salva ao confirmar", async ({ page }) => {
  await entrar(page);
  await page.getByRole("button", { name: "Extrato", exact: true }).click();
  await page.getByLabel("Lançamento por texto").fill("gastei 45,90 na padaria bella vista ontem");
  await page.getByRole("button", { name: "Ler" }).click();

  const previa = page.getByRole("region", { name: "Prévia do lançamento" });
  await expect(previa).toBeVisible();
  await expect(previa.getByLabel("Descrição")).toHaveValue("Padaria bella vista");
  await expect(previa.getByLabel("Valor (R$)")).toHaveValue("45,90");
  await expect(previa).toContainText("Alimentação");
  await expect(page.getByRole("row").filter({ hasText: /Padaria bella vista/ })).toHaveCount(0);

  await previa.getByRole("button", { name: "Lançar" }).click();
  await expect(previa).toBeHidden();
  const linha = page.getByRole("row").filter({ hasText: /Padaria bella vista/ });
  await expect(linha).toContainText("-R$ 45,90");
});

test("login: senha errada mostra o erro e não entra", async ({ page }) => {
  await entrar(page, "senha-errada-123");
  await expect(page.getByRole("alert")).toHaveText("Usuário ou senha incorretos.");
  await expect(page.getByRole("button", { name: USER })).toHaveCount(0);
});
