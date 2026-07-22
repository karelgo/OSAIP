// AC-5: dark mode via the user menu, then a keyboard-only walk — Tab to a rail
// link, verify a visible focus ring, activate with Enter, and open ⌘K.
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("dark theme + keyboard-only navigation with visible focus", async ({ page }) => {
  await login(page, "admin@osaip.dev");

  await page.getByTestId("user-menu").click();
  await page.getByTestId("theme-dark").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  // Walk inside a project so rail links have real destinations. On "/", the rail
  // renders with an empty project key. Theme persists (localStorage + zustand).
  await page.goto("/p/demo");
  await expect(page.getByTestId("project-home")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  // Tab (bounded) until a rail link is focused whose target differs from the
  // current URL — the first rail item ("Flow") links to /p/demo itself.
  let targetHref: string | null = null;
  for (let i = 0; i < 50; i += 1) {
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => {
      const el = document.activeElement;
      if (!(el instanceof HTMLElement)) return null;
      return {
        railItem: el.getAttribute("data-rail-item"),
        href: el.getAttribute("href"),
        pathname: window.location.pathname,
      };
    });
    if (focused?.railItem && focused.href && focused.href !== focused.pathname) {
      targetHref = focused.href;
      break;
    }
  }
  expect(targetHref, "expected Tab to reach a rail link").not.toBeNull();

  // Focus must be visible: Tailwind's focus-visible ring is a box-shadow (outline
  // would also count). Keyboard focus ⇒ :focus-visible applies.
  const ring = await page.evaluate(() => {
    const el = document.activeElement;
    if (!(el instanceof HTMLElement)) return null;
    const style = window.getComputedStyle(el);
    return { boxShadow: style.boxShadow, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
  });
  expect(ring).not.toBeNull();
  const hasRing =
    (ring!.boxShadow !== "" && ring!.boxShadow !== "none") ||
    (ring!.outlineStyle !== "none" && ring!.outlineWidth !== "0px");
  expect(hasRing, `focus ring missing: ${JSON.stringify(ring)}`).toBe(true);

  // Enter activates the link (client-side navigation).
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`${targetHref}$`));

  // ⌘K / Ctrl+K opens the omnibar from anywhere in the shell.
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByTestId("omnibar-input")).toBeVisible();
});
