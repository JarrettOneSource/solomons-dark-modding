import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

const nodeGlobals = {
  Buffer: "readonly",
  console: "readonly",
  process: "readonly",
};

export default tseslint.config(
  {
    ignores: ["dist/**", "node_modules/**", "assets/fixtures/**"],
  },
  eslint.configs.recommended,
  ...tseslint.configs.strictTypeChecked.map((configuration) => ({
    ...configuration,
    files: ["**/*.ts"],
  })),
  {
    files: ["**/*.ts"],
    languageOptions: {
      globals: nodeGlobals,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-confusing-void-expression": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/no-unnecessary-condition": "error",
      "@typescript-eslint/no-unsafe-argument": "error",
      "@typescript-eslint/no-unsafe-assignment": "error",
      "@typescript-eslint/no-unsafe-call": "error",
      "@typescript-eslint/no-unsafe-member-access": "error",
      "@typescript-eslint/no-unsafe-return": "error",
      "@typescript-eslint/restrict-template-expressions": [
        "error",
        { allowNumber: true },
      ],
    },
  },
  {
    files: ["**/*.js", "**/*.mjs"],
    languageOptions: {
      globals: nodeGlobals,
    },
  },
);
