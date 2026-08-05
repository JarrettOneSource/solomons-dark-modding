export interface Provenance {
  readonly sourceBundleFilename: string;
  readonly recordIndex: number;
  readonly sourceBytesSha256: string;
}

export interface AtlasDescriptor {
  readonly id: string;
  readonly file: string;
  readonly width: number;
  readonly height: number;
  readonly bytes: number;
  readonly sha256: string;
  readonly provenance: Provenance;
}

export interface AssetRect {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface AssetPoint {
  readonly x: number;
  readonly y: number;
}

export interface AssetEntry {
  readonly kind: "sprite" | "loose-image";
  readonly atlas: string;
  readonly rect: AssetRect;
  readonly pivot: AssetPoint;
  readonly logicalSize: {
    readonly width: number;
    readonly height: number;
  };
  readonly rotated: boolean;
  readonly points: readonly AssetPoint[];
  readonly provenance: Provenance & {
    readonly sourceOffset: number;
    readonly sourceLength: number;
  };
}

export interface FontGroup {
  readonly atlas: string;
  readonly firstRecord: number;
  readonly lastRecord: number;
  readonly metrics: readonly [number, number, number];
  readonly kerning: readonly {
    readonly leftGlyphId: number;
    readonly rightGlyphId: number;
    readonly adjustment: number;
  }[];
  readonly glyphs: Readonly<Record<string, string>>;
  readonly provenance: Provenance & {
    readonly sourceOffset: number;
    readonly sourceLength: number;
  };
}

export interface SpecialDrawResolver {
  readonly kind: "framebuffer-clear" | "textured-quad" | "system-font";
  readonly sourceGoldenFilename: string;
}

export interface PackDescriptor {
  readonly file: string;
  readonly bytes: number;
  readonly sha256: string;
  readonly entryCount: number;
}

export interface AssetManifest {
  readonly schema: "solomon-dark-web-asset-manifest-v1";
  readonly nativeIdFormat: "<Atlas>.<record-index>";
  readonly sources: {
    readonly bundleDecoder: "tools/extract_bundles.py";
    readonly boneyardDecoder: "tools/decode_boneyard_scripts.py";
    readonly nativeAssetObjectMap: string;
    readonly nativeSceneAtlasSpans: string;
    readonly nativeContentInventory: string;
  };
  readonly summary: {
    readonly atlasCount: number;
    readonly bundleAtlasCount: number;
    readonly looseAtlasCount: number;
    readonly spriteCount: number;
    readonly aliasCount: number;
    readonly fontGroupCount: number;
  };
  readonly atlases: readonly AtlasDescriptor[];
  readonly entries: Readonly<Record<string, AssetEntry>>;
  readonly aliases: Readonly<Record<string, string>>;
  readonly fontGroups: Readonly<Record<string, FontGroup>>;
  readonly specialDraws: Readonly<Record<string, SpecialDrawResolver>>;
  readonly packs: {
    readonly boneyards: PackDescriptor;
    readonly recipes: PackDescriptor;
    readonly waves: PackDescriptor;
  };
}

export interface BundleGroundTruth {
  readonly name: string;
  readonly bundlePath: string;
  readonly bundleBytes: number;
  readonly bundleSha256: string;
  readonly recordCount: number;
  readonly atlasPath: string;
  readonly atlasBytes: number;
  readonly atlasSha256: string;
  readonly atlasWidth: number;
  readonly atlasHeight: number;
}

export interface FileGroundTruth {
  readonly path: string;
  readonly bytes: number;
  readonly sha256: string;
}

export interface AssetGroundTruth {
  readonly bundles: readonly BundleGroundTruth[];
  readonly looseImages: readonly (FileGroundTruth & {
    readonly width: number;
    readonly height: number;
  })[];
  readonly boneyards: readonly FileGroundTruth[];
  readonly wave: FileGroundTruth;
  readonly waveFlags: ReadonlyMap<string, number>;
}

export interface BuildInputs {
  readonly repoRoot: string;
  readonly retailRoot: string;
  readonly outputRoot: string;
  readonly pythonExecutable: string;
  readonly groundTruth: AssetGroundTruth;
  readonly includeLoadingArt: boolean;
}

export interface OutputFileHash {
  readonly file: string;
  readonly bytes: number;
  readonly sha256: string;
}

export interface BuildResult {
  readonly manifest: AssetManifest;
  readonly files: readonly OutputFileHash[];
  readonly outputTreeSha256: string;
  readonly categoryBytes: {
    readonly atlases: number;
    readonly boneyards: number;
    readonly waves: number;
    readonly recipes: number;
    readonly metadata: number;
    readonly total: number;
  };
}
