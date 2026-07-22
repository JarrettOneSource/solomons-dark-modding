using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using SolomonDarkModLauncher.Commands;
using SolomonDarkModLauncher.Launch;
using SolomonDarkModLauncher.Mods;
using SolomonDarkModLauncher.Staging;
using SolomonDarkModLauncher.UI.Infrastructure;

var tests = new (string Name, Func<Task> Run)[]
{
    ("website package install and cache", TestWebsitePackageInstallAsync),
    ("downloaded package traversal rejection", TestDownloadedPackageTraversalAsync),
    ("downloaded native payload rejection", TestDownloadedNativePayloadAsync),
    ("website lobby preflight", TestWebsiteLobbyPreflightAsync),
    ("exact manual catalog", TestExactManualCatalogAsync),
    ("invalid Boneyard rejection", TestInvalidBoneyardRejectionAsync),
    ("automatic website sync with offline fallback", TestAutomaticWebsiteSyncAsync),
    ("website join URI", TestWebsiteJoinUriAsync)
};

var failures = 0;
foreach (var test in tests)
{
    try
    {
        await test.Run();
        Console.WriteLine($"PASS {test.Name}");
    }
    catch (Exception exception)
    {
        failures++;
        Console.Error.WriteLine($"FAIL {test.Name}: {exception}");
    }
}

return failures == 0 ? 0 : 1;

static async Task TestWebsitePackageInstallAsync()
{
    var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
    {
        ["manifest.json"] = Encoding.UTF8.GetBytes(
            """
            {
              "id": "tests.combined",
              "name": "Combined Test",
              "version": "1.0.0",
              "priority": 20,
              "overlays": [
                {
                  "target": "sandbox/DarkCloud/mylevels/Contract Arena.boneyard",
                  "source": "files/Contract Arena.boneyard",
                  "format": "boneyard"
                },
                {
                  "target": "images/Skills.png",
                  "source": "files/Skills.png"
                }
              ],
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua",
                "requiredCapabilities": [],
                "optionalCapabilities": ["ui"]
              }
            }
            """),
        ["files/Contract Arena.boneyard"] = BoneyardFixture(),
        ["files/Skills.png"] = "website art contract"u8.ToArray(),
        ["scripts/main.lua"] = Encoding.UTF8.GetBytes("return true\n")
    };
    var package = CreateZip(entries);
    var required = new MultiplayerModDescriptor(
        "tests.combined",
        "1.0.0",
        ComputeContentHash(entries));
    var resolved = new WebsiteResolvedMod(
        required.Id,
        required.Version,
        required.ContentSha256,
        Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant(),
        "api/mods/tests/versions/1/download");

    var cacheRoot = CreateTemporaryDirectory();
    try
    {
        using var client = new HttpClient(new PackageHandler(package))
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var installed = await WebsiteModPackageInstaller.InstallAsync(
            client,
            resolved,
            required,
            cacheRoot,
            CancellationToken.None);
        Require(installed.Manifest.Id == required.Id, "installed manifest id changed");
        Require(installed.RequiresLuaRuntime, "combined package did not retain Lua runtime");
        Require(installed.Manifest.Overlays.Count == 2, "combined package did not retain Boneyard and art overlays");
        Require(File.Exists(Path.Combine(installed.RootPath, "scripts", "main.lua")), "Lua script missing");
        Require(
            File.Exists(Path.Combine(installed.RootPath, "files", "Contract Arena.boneyard")),
            "Boneyard missing");

        var stageRoot = Path.Combine(cacheRoot, "stage");
        Directory.CreateDirectory(stageRoot);
        Require(
            OverlayStageMaterializer.Materialize(stageRoot, [installed]) == 2,
            "combined package overlays were not materialized");
        var stagedBoneyard = Path.Combine(
            stageRoot,
            "sandbox",
            "DarkCloud",
            "mylevels",
            "Contract Arena.boneyard");
        Require(File.Exists(stagedBoneyard), "custom Boneyard was staged outside the native sandbox path");
        Require(
            File.ReadAllBytes(stagedBoneyard).SequenceEqual(BoneyardFixture()),
            "staged custom Boneyard bytes changed");
        var stagedArt = Path.Combine(stageRoot, "images", "Skills.png");
        Require(File.Exists(stagedArt), "website art overlay was not staged under images/");
        Require(
            File.ReadAllBytes(stagedArt).SequenceEqual(entries["files/Skills.png"]),
            "staged website art bytes changed");

        var cached = WebsiteModPackageInstaller.TryLoadExact(installed.RootPath, required);
        Require(cached is not null, "exact cached package was not reusable");
    }
    finally
    {
        Directory.Delete(cacheRoot, recursive: true);
    }
}

static async Task TestDownloadedPackageTraversalAsync()
{
    var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
    {
        ["manifest.json"] = Encoding.UTF8.GetBytes(
            """
            {
              "id": "tests.traversal",
              "name": "Traversal Test",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              }
            }
            """),
        ["scripts/main.lua"] = Encoding.UTF8.GetBytes("return true\n"),
        ["../outside.txt"] = Encoding.UTF8.GetBytes("must not escape")
    };
    var package = CreateZip(entries);
    var required = new MultiplayerModDescriptor(
        "tests.traversal",
        "1.0.0",
        ComputeContentHash(entries));
    var resolved = new WebsiteResolvedMod(
        required.Id,
        required.Version,
        required.ContentSha256,
        Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant(),
        "api/mods/tests/versions/1/download");
    var cacheRoot = CreateTemporaryDirectory();
    try
    {
        using var client = new HttpClient(new PackageHandler(package))
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var rejected = false;
        try
        {
            await WebsiteModPackageInstaller.InstallAsync(
                client,
                resolved,
                required,
                cacheRoot,
                CancellationToken.None);
        }
        catch (InvalidDataException)
        {
            rejected = true;
        }
        Require(rejected, "downloaded ZIP traversal was accepted");
    }
    finally
    {
        Directory.Delete(cacheRoot, recursive: true);
    }
}

static async Task TestDownloadedNativePayloadAsync()
{
    var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
    {
        ["manifest.json"] = Encoding.UTF8.GetBytes(
            """
            {
              "id": "tests.hidden-native",
              "name": "Hidden Native Test",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              }
            }
            """),
        ["scripts/main.lua"] = Encoding.UTF8.GetBytes("return true\n"),
        ["native/hidden.DLL"] = Encoding.UTF8.GetBytes("not a dll")
    };
    var package = CreateZip(entries);
    var required = new MultiplayerModDescriptor(
        "tests.hidden-native",
        "1.0.0",
        ComputeContentHash(entries));
    var resolved = new WebsiteResolvedMod(
        required.Id,
        required.Version,
        required.ContentSha256,
        Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant(),
        "api/mods/tests/versions/1/download");
    var cacheRoot = CreateTemporaryDirectory();
    try
    {
        using var client = new HttpClient(new PackageHandler(package))
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var rejected = false;
        try
        {
            await WebsiteModPackageInstaller.InstallAsync(
                client,
                resolved,
                required,
                cacheRoot,
                CancellationToken.None);
        }
        catch (InvalidDataException)
        {
            rejected = true;
        }
        Require(rejected, "downloaded DLL payload was accepted");
    }
    finally
    {
        Directory.Delete(cacheRoot, recursive: true);
    }
}

static Task TestExactManualCatalogAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        var boneyardRoot = Path.Combine(root, "boneyard");
        Directory.CreateDirectory(Path.Combine(boneyardRoot, "files"));
        File.WriteAllText(
            Path.Combine(boneyardRoot, "manifest.json"),
            """
            {
              "id": "tests.manual-boneyard",
              "name": "Manual Boneyard",
              "version": "1.0.0",
              "overlays": [{
                "target": "data/levels/survival.boneyard",
                "source": "files/survival.boneyard"
              }]
            }
            """);
        File.WriteAllBytes(
            Path.Combine(boneyardRoot, "files", "survival.boneyard"),
            BoneyardFixture());

        var luaRoot = Path.Combine(root, "lua");
        Directory.CreateDirectory(Path.Combine(luaRoot, "scripts"));
        File.WriteAllText(
            Path.Combine(luaRoot, "manifest.json"),
            """
            {
              "id": "tests.manual-lua",
              "name": "Manual Lua",
              "version": "1.0.0",
              "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua"
              },
              "requiredMods": ["tests.manual-boneyard"]
            }
            """);
        File.WriteAllText(Path.Combine(luaRoot, "scripts", "main.lua"), "return true\n");

        var boneyard = ModDiscovery.DiscoverRoot(boneyardRoot);
        var lua = ModDiscovery.DiscoverRoot(luaRoot);
        var catalog = ModCatalog.CreateExact([lua, boneyard]);
        Require(catalog.EnabledMods.Count == 2, "exact manual set was not fully enabled");
        Require(catalog.IsEnabled("tests.manual-boneyard"), "manual dependency was not enabled");
        Require(catalog.IsEnabled("tests.manual-lua"), "manual Lua mod was not enabled");

        var missingDependencyRejected = false;
        try
        {
            ModCatalog.CreateExact([lua]);
        }
        catch (InvalidOperationException)
        {
            missingDependencyRejected = true;
        }
        Require(missingDependencyRejected, "exact sets accepted a missing dependency");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestInvalidBoneyardRejectionAsync()
{
    var root = CreateTemporaryDirectory();
    try
    {
        Directory.CreateDirectory(Path.Combine(root, "files"));
        File.WriteAllText(
            Path.Combine(root, "manifest.json"),
            """
            {
              "id": "tests.invalid-boneyard",
              "name": "Invalid Boneyard",
              "version": "1.0.0",
              "overlays": [{
                "target": "data/levels/survival.boneyard",
                "source": "files/survival.boneyard",
                "format": "boneyard"
              }]
            }
            """);
        File.WriteAllBytes(Path.Combine(root, "files", "survival.boneyard"), []);

        var rejected = false;
        try
        {
            ModDiscovery.DiscoverRoot(root);
        }
        catch (InvalidDataException)
        {
            rejected = true;
        }
        Require(rejected, "a zero-byte Boneyard was accepted");

        File.WriteAllBytes(
            Path.Combine(root, "files", "survival.boneyard"),
            BoneyardFixture());
        File.WriteAllText(
            Path.Combine(root, "manifest.json"),
            """
            {
              "id": "tests.wrong-boneyard-target",
              "name": "Wrong Boneyard Target",
              "version": "1.0.0",
              "overlays": [{
                "target": "DarkCloud/mylevels/Wrong.boneyard",
                "source": "files/survival.boneyard",
                "format": "boneyard"
              }]
            }
            """);
        rejected = false;
        try
        {
            ModDiscovery.DiscoverRoot(root);
        }
        catch (InvalidOperationException)
        {
            rejected = true;
        }
        Require(rejected, "a custom Boneyard target without the native sandbox prefix was accepted");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }

    return Task.CompletedTask;
}

static Task TestAutomaticWebsiteSyncAsync()
{
    var direct = LauncherCommandParser.Parse(
        ["launch", "--multiplayer", "join", "--lobby-id", "123"]);
    Require(direct.LobbyTicket is null, "direct P2P lobby join unexpectedly has a website ticket");
    Require(
        direct.LobbyHost.DirectoryBaseUrl == LobbyHostOptions.DefaultDirectoryBaseUrl,
        "direct P2P lobby join did not retain the default website fallback");

    var website = LauncherCommandParser.Parse(
        [
            "launch",
            "--multiplayer", "join",
            "--lobby-id", "123",
            "--directory-url", "https://mods.example.test/community",
            "--lobby-ticket", "signed-ticket"
        ]);
    Require(website.LobbyTicket == "signed-ticket", "website ticket was not retained");
    Require(
        website.LobbyHost.DirectoryBaseUrl == "https://mods.example.test/community",
        "website directory path base was lost");

    var invalidRejected = false;
    try
    {
        LauncherCommandParser.Parse(
            ["launch", "--multiplayer", "join", "--lobby-ticket", "signed-ticket"]);
    }
    catch (InvalidOperationException)
    {
        invalidRejected = true;
    }
    Require(invalidRejected, "website ticket was accepted without a concrete lobby id");
    return Task.CompletedTask;
}

static async Task TestWebsiteLobbyPreflightAsync()
{
    var entries = new Dictionary<string, byte[]>(StringComparer.Ordinal)
    {
        ["manifest.json"] = Encoding.UTF8.GetBytes(
            """
            {
              "id": "tests.preflight",
              "name": "Preflight Test",
              "version": "3.0.0",
              "overlays": [{
                "target": "data/levels/survival.boneyard",
                "source": "files/survival.boneyard"
              }]
            }
            """),
        ["files/survival.boneyard"] = BoneyardFixture()
    };
    var package = CreateZip(entries);
    var required = new MultiplayerModDescriptor(
        "tests.preflight",
        "3.0.0",
        ComputeContentHash(entries));
    var packageSha256 = Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant();
    var root = CreateTemporaryDirectory();
    try
    {
        var unrelatedRoot = Path.Combine(root, "unrelated");
        Directory.CreateDirectory(Path.Combine(unrelatedRoot, "files"));
        File.WriteAllText(
            Path.Combine(unrelatedRoot, "manifest.json"),
            """
            {
              "id": "tests.unrelated",
              "name": "Unrelated",
              "version": "1.0.0",
              "overlays": [{
                "target": "data/unrelated.txt",
                "source": "files/unrelated.txt"
              }]
            }
            """);
        File.WriteAllText(Path.Combine(unrelatedRoot, "files", "unrelated.txt"), "unrelated");
        var localCatalog = ModCatalog.CreateExact([ModDiscovery.DiscoverRoot(unrelatedRoot)]);

        var handler = new LobbyDirectoryHandler(package, required, packageSha256);
        using var client = new HttpClient(handler)
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var cacheRoot = Path.Combine(root, "cache");
        var result = await LobbyModSynchronizer.SynchronizeAsync(
            localCatalog,
            42,
            ticket: null,
            cacheRoot,
            client);
        Require(result.UsedWebsite, "available website unexpectedly selected offline fallback");
        Require(result.RequiredModCount == 1, "preflight required count changed");
        Require(result.DownloadedModCount == 1, "missing website mod was not downloaded");
        Require(result.Catalog.EnabledMods.Count == 1, "preflight staged extra local mods");
        Require(result.Catalog.FindById(required.Id) is not null, "required website mod was not selected");
        Require(result.Catalog.FindById("tests.unrelated") is null, "unrelated local mod remained selected");
        Require(handler.JoinManifestRequests == 1, "preflight did not request the join manifest once");
        Require(handler.ResolveRequests == 1, "preflight did not resolve the missing package once");
        Require(handler.DownloadRequests == 1, "preflight did not download the missing package once");

        var manualCatalog = ModCatalog.CreateExact(result.Catalog.EnabledMods);
        var manualHandler = new LobbyDirectoryHandler(
            package,
            required,
            packageSha256,
            rejectResolution: true);
        using var manualClient = new HttpClient(manualHandler)
        {
            BaseAddress = new Uri("https://mods.example.test/community/")
        };
        var manualResult = await LobbyModSynchronizer.SynchronizeAsync(
            manualCatalog,
            42,
            ticket: null,
            Path.Combine(root, "unused-cache"),
            manualClient);
        Require(manualResult.ReusedManualModCount == 1, "exact manual package was not reused");
        Require(manualResult.DownloadedModCount == 0, "exact manual package was downloaded again");
        Require(manualHandler.ResolveRequests == 0, "manual reuse unnecessarily called resolution");

        using var offlineClient = new HttpClient(new OfflineDirectoryHandler())
        {
            BaseAddress = new Uri("https://offline.example.test/")
        };
        var offlineResult = await LobbyModSynchronizer.SynchronizeAsync(
            manualCatalog,
            42,
            ticket: null,
            Path.Combine(root, "offline-cache"),
            offlineClient);
        Require(!offlineResult.UsedWebsite, "unavailable website did not select offline fallback");
        Require(
            offlineResult.Catalog.EnabledMods.Count == 1 &&
            offlineResult.Catalog.IsEnabled(required.Id),
            "offline fallback changed the locally enabled exact mod set");
    }
    finally
    {
        Directory.Delete(root, recursive: true);
    }
}

static Task TestWebsiteJoinUriAsync()
{
    var valid =
        "solomondarkrevived://join/123?directory=https%3A%2F%2Fmods.example.test%2Fcommunity&ticket=signed-token";
    Require(LauncherJoinUri.TryParse(valid, out var activation), "valid website join URI was rejected");
    Require(activation.LobbyId == 123, "website join URI lobby id changed");
    Require(
        activation.DirectoryBaseUrl == "https://mods.example.test/community",
        "website join URI directory changed");
    Require(activation.Ticket == "signed-token", "website join URI ticket changed");

    Require(
        !LauncherJoinUri.TryParse("solomondarkrevived://join/123", out _),
        "website join URI without directory was accepted");
    Require(
        !LauncherJoinUri.TryParse(
            "solomondarkrevived://join/123?directory=http%3A%2F%2Fevil.example.test",
            out _),
        "remote plaintext website origin was accepted");
    Require(
        !LauncherJoinUri.TryParse(
            "solomondarkrevived://join/123?directory=https%3A%2F%2Fmods.example.test&extra=x",
            out _),
        "unknown website join URI parameter was accepted");
    return Task.CompletedTask;
}

static byte[] CreateZip(IReadOnlyDictionary<string, byte[]> entries)
{
    using var buffer = new MemoryStream();
    using (var archive = new ZipArchive(buffer, ZipArchiveMode.Create, leaveOpen: true))
    {
        foreach (var pair in entries)
        {
            var entry = archive.CreateEntry(pair.Key, CompressionLevel.Optimal);
            using var stream = entry.Open();
            stream.Write(pair.Value);
        }
    }
    return buffer.ToArray();
}

static byte[] BoneyardFixture() =>
    File.ReadAllBytes(Path.Combine(
        AppContext.BaseDirectory,
        "fixtures",
        "flat_multiplayer_test.boneyard"));

static string ComputeContentHash(IReadOnlyDictionary<string, byte[]> entries)
{
    using var aggregate = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
    foreach (var pair in entries.OrderBy(pair => pair.Key, StringComparer.Ordinal))
    {
        var fileHash = Convert.ToHexString(SHA256.HashData(pair.Value)).ToLowerInvariant();
        aggregate.AppendData(Encoding.UTF8.GetBytes($"{pair.Key}\0{fileHash}\n"));
    }
    return Convert.ToHexString(aggregate.GetHashAndReset()).ToLowerInvariant();
}

static string CreateTemporaryDirectory()
{
    var path = Path.Combine(Path.GetTempPath(), $"sdr-launcher-contract-{Guid.NewGuid():N}");
    Directory.CreateDirectory(path);
    return path;
}

static void Require(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

file sealed class PackageHandler(byte[] package) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        if (request.Method != HttpMethod.Get ||
            request.RequestUri?.AbsoluteUri !=
            "https://mods.example.test/community/api/mods/tests/versions/1/download")
        {
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
        }

        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(package)
        });
    }
}

file sealed class OfflineDirectoryHandler : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken) =>
        throw new HttpRequestException("Website unavailable for contract test.");
}

file sealed class LobbyDirectoryHandler(
    byte[] package,
    MultiplayerModDescriptor required,
    string packageSha256,
    bool rejectResolution = false) : HttpMessageHandler
{
    public int JoinManifestRequests { get; private set; }
    public int ResolveRequests { get; private set; }
    public int DownloadRequests { get; private set; }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var path = request.RequestUri?.AbsolutePath;
        if (request.Method == HttpMethod.Get &&
            path == "/community/api/lobbies/42/join-manifest")
        {
            JoinManifestRequests++;
            return Json(
                $$"""
                {"lobbyId":"42","mods":[{"id":"{{required.Id}}","version":"{{required.Version}}","contentSha256":"{{required.ContentSha256}}"}]}
                """);
        }

        if (request.Method == HttpMethod.Post && path == "/community/api/mods/resolve")
        {
            ResolveRequests++;
            if (rejectResolution)
            {
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.InternalServerError));
            }
            return Json(
                $$"""
                {"mods":[{"id":"{{required.Id}}","version":"{{required.Version}}","contentSha256":"{{required.ContentSha256}}","packageSha256":"{{packageSha256}}","downloadUrl":"api/mods/tests/versions/1/download"}],"missing":[]}
                """);
        }

        if (request.Method == HttpMethod.Get &&
            path == "/community/api/mods/tests/versions/1/download")
        {
            DownloadRequests++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(package)
            });
        }

        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
    }

    private static Task<HttpResponseMessage> Json(string value) =>
        Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(value, Encoding.UTF8, "application/json")
        });
}
