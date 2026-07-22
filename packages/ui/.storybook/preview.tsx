import * as React from "react";
import type { Decorator, Preview } from "@storybook/react";
import "../src/styles/index.css";

// Theme + density land on <html> exactly like the app shell sets them
// (data-theme="light" | "dark" | "system", data-density).
const withThemeAndDensity: Decorator = (Story, context) => {
  const theme = (context.globals.theme as string | undefined) ?? "light";
  const density = (context.globals.density as string | undefined) ?? "comfortable";
  React.useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    root.setAttribute("data-density", density);
  }, [theme, density]);
  return <Story />;
};

const preview: Preview = {
  globalTypes: {
    theme: {
      description: "Color theme",
      toolbar: {
        title: "Theme",
        icon: "mirror",
        items: ["light", "dark", "system"],
        dynamicTitle: true,
      },
    },
    density: {
      description: "Density",
      toolbar: {
        title: "Density",
        icon: "grow",
        items: ["comfortable", "compact"],
        dynamicTitle: true,
      },
    },
  },
  initialGlobals: {
    theme: "light",
    density: "comfortable",
  },
  decorators: [withThemeAndDensity],
  parameters: {
    layout: "centered",
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
  },
};

export default preview;
