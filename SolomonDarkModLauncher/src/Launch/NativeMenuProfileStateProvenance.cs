using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SolomonDarkModLauncher.Launch;

internal static class NativeMenuProfileStateProvenance
{
    internal const string ReceiptSchema =
        "solomon-dark-native-menu-profile-state-v1";
    internal const string IdentitySchema =
        "solomon-dark-native-menu-profile-state-input-v1";
    internal const string ReceiptFilename =
        "native-menu-profile-state.json";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true
    };

    public static NativeMenuProfileStateReceipt Materialize(
        string stageRootPath,
        LaunchOptions options,
        bool freshInstall,
        bool retailAppDataSeeded)
    {
        if (string.IsNullOrWhiteSpace(options.ProfileRootPath))
        {
            throw new InvalidOperationException(
                "Profile-state provenance requires an isolated profile root.");
        }

        var baselineMode = freshInstall
            ? "fresh_install"
            : options.TemporaryProfile
                ? "temporary_profile"
                : "persistent_profile";
        var roots = new[]
        {
            new StateRoot(
                "stage_sandbox",
                Path.Combine(stageRootPath, "sandbox")),
            new StateRoot("isolated_profile", options.ProfileRootPath)
        };
        var files = roots
            .SelectMany(ReadFiles)
            .OrderBy(file => file.Root, StringComparer.Ordinal)
            .ThenBy(file => file.RelativePath, StringComparer.Ordinal)
            .ToArray();
        var identityPayload = new
        {
            schema = IdentitySchema,
            baseline_mode = baselineMode,
            source_sandbox_excluded = freshInstall,
            retail_appdata_seeded = retailAppDataSeeded,
            files = files.Select(file => new
            {
                root = file.Root,
                relative_path = file.RelativePath,
                bytes = file.Bytes,
                sha256 = file.Sha256
            })
        };
        var canonicalIdentityJson = JsonSerializer.Serialize(identityPayload);
        var identitySha256 = Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes(canonicalIdentityJson)))
            .ToLowerInvariant();
        var receiptDirectory = Path.Combine(stageRootPath, ".sdmod");
        Directory.CreateDirectory(receiptDirectory);
        var receiptPath = Path.Combine(receiptDirectory, ReceiptFilename);
        var receipt = new NativeMenuProfileStateReceipt(
            ReceiptSchema,
            identitySha256,
            baselineMode,
            freshInstall,
            retailAppDataSeeded,
            files,
            Path.GetFullPath(Path.Combine(stageRootPath, "sandbox")),
            Path.GetFullPath(options.ProfileRootPath),
            DateTimeOffset.UtcNow,
            receiptPath);
        WriteAtomic(receiptPath, receipt);
        return receipt;
    }

    private static IEnumerable<NativeMenuProfileStateFile> ReadFiles(
        StateRoot root)
    {
        if (!Directory.Exists(root.Path))
        {
            yield break;
        }

        var options = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            AttributesToSkip = FileAttributes.ReparsePoint,
            IgnoreInaccessible = false,
            ReturnSpecialDirectories = false
        };
        foreach (var filePath in Directory.EnumerateFiles(
                     root.Path,
                     "*",
                     options))
        {
            var relativePath = Path.GetRelativePath(root.Path, filePath)
                .Replace(Path.DirectorySeparatorChar, '/');
            if (relativePath == ".." || relativePath.StartsWith("../", StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "Profile-state provenance resolved a file outside its declared root.");
            }

            var file = new FileInfo(filePath);
            using var stream = File.OpenRead(filePath);
            var sha256 = Convert.ToHexString(SHA256.HashData(stream))
                .ToLowerInvariant();
            yield return new NativeMenuProfileStateFile(
                root.Name,
                relativePath,
                file.Length,
                sha256);
        }
    }

    private static void WriteAtomic(
        string receiptPath,
        NativeMenuProfileStateReceipt receipt)
    {
        var temporaryPath = receiptPath + "." + Guid.NewGuid().ToString("N") +
            ".tmp";
        try
        {
            File.WriteAllText(
                temporaryPath,
                JsonSerializer.Serialize(receipt, JsonOptions) +
                    Environment.NewLine,
                new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            File.Move(temporaryPath, receiptPath, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }

    private sealed record StateRoot(string Name, string Path);
}

internal sealed record NativeMenuProfileStateFile(
    string Root,
    string RelativePath,
    long Bytes,
    string Sha256);

internal sealed record NativeMenuProfileStateReceipt(
    string Schema,
    string ProfileStateIdentitySha256,
    string BaselineMode,
    bool SourceSandboxExcluded,
    [property: JsonPropertyName("retail_appdata_seeded")]
    bool RetailAppDataSeeded,
    IReadOnlyList<NativeMenuProfileStateFile> Files,
    string StageSandboxRoot,
    string IsolatedProfileRoot,
    DateTimeOffset RecordedAtUtc,
    string ReceiptPath);
