import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, type Plugin } from "vite";

const workspace = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(workspace, "..");

const contentTypes: Readonly<Record<string, string>> = {
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
};

function assetpackServer(assetRoot: string | undefined): Plugin {
  return {
    name: "solomon-dark-assetpack",
    configureServer(server): void {
      if (assetRoot === undefined || assetRoot.length === 0) {
        return;
      }
      const resolvedRoot = path.resolve(assetRoot);
      server.middlewares.use("/assetpack", (request, response, next) => {
        const pathname = decodeURIComponent(new URL(request.url ?? "/", "http://local").pathname);
        const candidate = path.resolve(resolvedRoot, `.${pathname}`);
        const relative = path.relative(resolvedRoot, candidate);
        if (relative.startsWith("..") || path.isAbsolute(relative)) {
          response.statusCode = 403;
          response.end("assetpack path escapes its root");
          return;
        }
        void stat(candidate).then((metadata) => {
          if (!metadata.isFile()) {
            next();
            return;
          }
          response.statusCode = 200;
          response.setHeader(
            "Content-Type",
            contentTypes[path.extname(candidate).toLowerCase()] ?? "application/octet-stream",
          );
          createReadStream(candidate).pipe(response);
        }).catch(() => {
          next();
        });
      });
    },
  };
}

export default defineConfig({
  root: workspace,
  publicDir: false,
  plugins: [assetpackServer(process.env.WEBGAME_ASSET_ROOT)],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    fs: {
      allow: [repository],
    },
  },
});
