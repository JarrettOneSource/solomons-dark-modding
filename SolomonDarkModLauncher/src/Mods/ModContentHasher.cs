using System.Security.Cryptography;
using System.Text;

namespace SolomonDarkModLauncher.Mods;

internal static class ModContentHasher
{
    public static string HashDirectory(string rootPath)
    {
        using var aggregate = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var files = Directory.EnumerateFiles(rootPath, "*", SearchOption.AllDirectories)
            .Select(path => new
            {
                FullPath = path,
                RelativePath = Path.GetRelativePath(rootPath, path)
                    .Replace(Path.DirectorySeparatorChar, '/')
                    .Replace(Path.AltDirectorySeparatorChar, '/')
            })
            .OrderBy(file => file.RelativePath, StringComparer.Ordinal);
        foreach (var file in files)
        {
            var record = $"{file.RelativePath}\0{HashFile(file.FullPath)}\n";
            aggregate.AppendData(Encoding.UTF8.GetBytes(record));
        }

        return Convert.ToHexString(aggregate.GetHashAndReset()).ToLowerInvariant();
    }

    public static string HashFile(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    public static string HashText(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
