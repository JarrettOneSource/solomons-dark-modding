import type {
  AssetEntry,
  AssetManifest,
  AtlasDescriptor,
  FontGroup,
  SpecialDrawResolver,
} from "../assets/types.js";
import type { MenuCatalog, MenuElement } from "./menu-catalog.js";

export interface ResolvedAsset {
  readonly requestedId: string;
  readonly canonicalId: string;
  readonly entry: AssetEntry;
  readonly atlas: AtlasDescriptor;
}

function assertManifestShape(value: unknown): asserts value is AssetManifest {
  if (
    value === null
    || typeof value !== "object"
    || (value as { schema?: unknown }).schema !== "solomon-dark-web-asset-manifest-v1"
  ) {
    throw new Error("assetpack manifest is missing or has the wrong schema");
  }
}

export class ManifestAssets {
  readonly #manifest: AssetManifest;
  readonly #atlases: ReadonlyMap<string, AtlasDescriptor>;

  public constructor(value: unknown) {
    assertManifestShape(value);
    this.#manifest = value;
    const atlases = new Map<string, AtlasDescriptor>();
    for (const atlas of value.atlases) {
      if (atlases.has(atlas.id)) {
        throw new Error(`assetpack manifest ambiguously defines atlas ${atlas.id}`);
      }
      atlases.set(atlas.id, atlas);
    }
    if (atlases.size === 0) {
      throw new Error("assetpack manifest contains no usable atlases");
    }
    this.#atlases = atlases;
  }

  public get manifest(): AssetManifest {
    return this.#manifest;
  }

  public resolve(id: string): ResolvedAsset {
    if (this.#manifest.specialDraws[id] !== undefined) {
      throw new Error(`assetpack manifest is ambiguous for ${id}: special draw and sprite lookup both apply`);
    }
    const direct = this.#manifest.entries[id];
    const aliasTarget = this.#manifest.aliases[id];
    if (direct !== undefined && aliasTarget !== undefined) {
      throw new Error(`assetpack manifest is ambiguous for ${id}: entry and alias both exist`);
    }
    const canonicalId = aliasTarget ?? id;
    if (aliasTarget !== undefined && this.#manifest.aliases[aliasTarget] !== undefined) {
      throw new Error(`assetpack manifest alias ${id} chains through ${aliasTarget}; resolution is ambiguous`);
    }
    const entry = direct ?? this.#manifest.entries[canonicalId];
    if (entry === undefined) {
      throw new Error(`assetpack manifest is missing required asset id ${id}`);
    }
    const atlas = this.#atlases.get(entry.atlas);
    if (atlas === undefined) {
      throw new Error(`assetpack asset ${id} names missing atlas ${entry.atlas}`);
    }
    return { requestedId: id, canonicalId, entry, atlas };
  }

  public special(id: string): SpecialDrawResolver {
    const special = this.#manifest.specialDraws[id];
    const direct = this.#manifest.entries[id];
    const alias = this.#manifest.aliases[id];
    if (special !== undefined && (direct !== undefined || alias !== undefined)) {
      throw new Error(`assetpack manifest is ambiguous for ${id}: special draw and sprite lookup both apply`);
    }
    if (special === undefined) {
      throw new Error(`assetpack manifest is missing required special draw id ${id}`);
    }
    return special;
  }

  public assertHubSceneAssets(draws: readonly Readonly<{ sprite: Readonly<{ id: string }> }>[]): void {
    if (draws.length !== 1319 || draws[0]?.sprite.id !== "native.framebuffer-clear") {
      throw new Error("assetpack hub audit did not reach the canonical 1,319-draw G12 witness");
    }
    let checked = 0;
    for (const draw of draws) {
      if (this.#manifest.specialDraws[draw.sprite.id] !== undefined) {
        this.special(draw.sprite.id);
      } else {
        this.resolve(draw.sprite.id);
      }
      checked += 1;
    }
    if (checked !== draws.length) {
      throw new Error("assetpack hub audit did not check every G12 draw");
    }
  }

  public font(id: string): FontGroup | SpecialDrawResolver {
    const group = this.#manifest.fontGroups[id];
    const special = this.#manifest.specialDraws[id];
    if (group !== undefined && special !== undefined) {
      throw new Error(`assetpack manifest is ambiguous for font ${id}`);
    }
    if (group === undefined && special === undefined) {
      throw new Error(`assetpack manifest is missing required font id ${id}`);
    }
    return group ?? special as SpecialDrawResolver;
  }

  public glyph(fontId: string, character: string): ResolvedAsset | null {
    if (character === " " || character === "\n" || character === "\t") {
      return null;
    }
    const font = this.font(fontId);
    if (!("glyphs" in font)) {
      throw new Error(`${fontId} is a system-font draw and has no assetpack glyph records`);
    }
    const assetId = font.glyphs[String(character.codePointAt(0))];
    if (assetId === undefined) {
      throw new Error(
        `assetpack font ${fontId} is missing glyph U+${character.codePointAt(0)?.toString(16).toUpperCase()}`,
      );
    }
    return this.resolve(assetId);
  }

  public assertShellAssets(catalog: MenuCatalog): void {
    let checkedElements = 0;
    for (const layout of catalog.layouts.values()) {
      for (const element of layout.elements) {
        this.#assertElement(element, layout.id);
        checkedElements += 1;
      }
    }
    if (checkedElements === 0) {
      throw new Error("assetpack shell audit did not reach any G11 layout elements");
    }
  }

  #assertElement(element: MenuElement, layoutId: string): void {
    if (element.kind === "art") {
      if (element.artId.length === 0) {
        throw new Error(`${layoutId}/${element.id} is art without an assetpack id`);
      }
      this.resolve(element.artId);
      return;
    }
    if (element.kind === "text" && element.fontId.length > 0) {
      const font = this.font(element.fontId);
      if ("glyphs" in font) {
        for (const character of element.text) {
          this.glyph(element.fontId, character);
        }
      }
    }
  }
}

export async function loadManifestAssets(url = "/assetpack/asset-manifest.json"): Promise<ManifestAssets> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`assetpack manifest failed to load from ${url}: HTTP ${response.status}`);
  }
  return new ManifestAssets(await response.json());
}
