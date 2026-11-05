// Lint for the browser modules in static/js (run: npx eslint@10.14.0). Leaflet is loaded as the global `L`.
const browser = ["document", "window", "localStorage", "navigator", "fetch", "AbortController", "URLSearchParams",
  "getComputedStyle", "matchMedia", "innerWidth", "history", "location", "getSelection", "URL", "Blob", "console",
  "setTimeout", "clearTimeout", "L"];

export default [{
  files: ["static/js/**/*.js", "tests/js/**/*.mjs"],
  languageOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    globals: Object.fromEntries(browser.map((g) => [g, "readonly"])),
  },
  rules: { "no-undef": "error", "no-unused-vars": ["error", { args: "none" }] },
}];
