using System.Net.Http.Json;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace SolomonDarkModLauncher.Steam;

internal static class SteamDirectoryAuthenticator
{
    private const string TicketIdentity = "solomon-dark-directory-v1";
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    public static async Task<SteamDirectorySession> AuthenticateAsync(
        string directoryBaseUrl,
        string? steamApiDllOverride,
        CancellationToken cancellationToken = default)
    {
        var steamConfiguration = SteamBootstrapConfiguration.CreateDefault(
            SteamBootstrapConfiguration.SpacewarDevelopmentAppId,
            steamApiDllOverride);
        var steamApiPath = SteamBootstrapMaterializer.ResolveSteamApiSourcePath(
            steamConfiguration)
            ?? throw new InvalidOperationException(
                "Steam directory authentication requires the packaged x86 steam_api.dll.");

        using var steam = new SteamWebApiTicketSession(steamApiPath);
        var ticket = steam.GetTicket(TicketIdentity, TimeSpan.FromSeconds(10));

        using var client = new HttpClient
        {
            BaseAddress = new Uri(directoryBaseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromSeconds(10)
        };
        using var response = await client.PostAsJsonAsync(
            "api/auth/steam/session",
            new SteamSessionRequest(ticket),
            JsonOptions,
            cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            var error = await ReadErrorAsync(response, cancellationToken);
            throw new InvalidOperationException(
                $"The lobby directory rejected Steam authentication ({(int)response.StatusCode}): {error}");
        }

        var session = await response.Content.ReadFromJsonAsync<SteamDirectorySession>(
            JsonOptions,
            cancellationToken);
        if (session is null || string.IsNullOrWhiteSpace(session.Token) ||
            string.IsNullOrWhiteSpace(session.SteamId))
        {
            throw new InvalidOperationException(
                "The lobby directory returned an incomplete Steam session.");
        }

        return session;
    }

    private static async Task<string> ReadErrorAsync(
        HttpResponseMessage response,
        CancellationToken cancellationToken)
    {
        try
        {
            var payload = await response.Content.ReadFromJsonAsync<DirectoryError>(
                JsonOptions,
                cancellationToken);
            return string.IsNullOrWhiteSpace(payload?.Error)
                ? response.ReasonPhrase ?? "request failed"
                : payload.Error;
        }
        catch (JsonException)
        {
            return response.ReasonPhrase ?? "request failed";
        }
    }

    private sealed record SteamSessionRequest(string Ticket);
    private sealed record DirectoryError(string? Error);

    private sealed class SteamWebApiTicketSession : IDisposable
    {
        private const int GetTicketForWebApiCallbackId = 168;
        private const int TicketHeaderBytes = 12;
        private const int MaximumTicketBytes = 2560;

        private readonly SteamManualDispatchSession dispatch_;
        private readonly SteamGetAuthTicketForWebApi getAuthTicket_;
        private readonly SteamCancelAuthTicket cancelAuthTicket_;
        private readonly nint steamUser_;
        private uint ticketHandle_;

        public SteamWebApiTicketSession(string steamApiPath)
        {
            dispatch_ = new SteamManualDispatchSession(steamApiPath);
            try
            {
                steamUser_ = dispatch_.GetInterface("SteamAPI_SteamUser_v023");
                getAuthTicket_ = dispatch_.Load<SteamGetAuthTicketForWebApi>(
                    "SteamAPI_ISteamUser_GetAuthTicketForWebApi");
                cancelAuthTicket_ = dispatch_.Load<SteamCancelAuthTicket>(
                    "SteamAPI_ISteamUser_CancelAuthTicket");
            }
            catch
            {
                Dispose();
                throw;
            }
        }

        public string GetTicket(string identity, TimeSpan timeout)
        {
            ticketHandle_ = getAuthTicket_(steamUser_, identity);
            if (ticketHandle_ == 0)
            {
                throw new InvalidOperationException(
                    "Steam did not issue a website authentication ticket.");
            }

            var deadline = DateTime.UtcNow + timeout;
            while (DateTime.UtcNow < deadline)
            {
                string? ticket = null;
                dispatch_.RunCallbacks(callback =>
                {
                    if (callback.CallbackId == GetTicketForWebApiCallbackId)
                    {
                        ticket = ReadTicket(callback);
                    }
                });
                if (ticket is not null)
                {
                    return ticket;
                }

                Thread.Sleep(10);
            }

            throw new TimeoutException(
                "Steam did not complete website authentication within 10 seconds.");
        }

        public void Dispose()
        {
            if (ticketHandle_ != 0 && steamUser_ != 0)
            {
                cancelAuthTicket_(steamUser_, ticketHandle_);
                ticketHandle_ = 0;
            }
            dispatch_.Dispose();
        }

        private string ReadTicket(SteamCallbackMessage callback)
        {
            if (callback.Parameter == 0 || callback.ParameterSize < TicketHeaderBytes)
            {
                throw new InvalidOperationException(
                    "Steam returned an incomplete website authentication callback.");
            }

            var handle = unchecked((uint)Marshal.ReadInt32(callback.Parameter, 0));
            var result = Marshal.ReadInt32(callback.Parameter, 4);
            var ticketBytes = Marshal.ReadInt32(callback.Parameter, 8);
            if (handle != ticketHandle_ || result != 1 ||
                ticketBytes is <= 0 or > MaximumTicketBytes ||
                callback.ParameterSize < TicketHeaderBytes + ticketBytes)
            {
                throw new InvalidOperationException(
                    "Steam rejected the website authentication ticket request.");
            }

            var ticket = new byte[ticketBytes];
            Marshal.Copy(callback.Parameter + TicketHeaderBytes, ticket, 0, ticket.Length);
            return Convert.ToHexString(ticket).ToLowerInvariant();
        }

        [UnmanagedFunctionPointer(CallingConvention.Cdecl, CharSet = CharSet.Ansi)]
        private delegate uint SteamGetAuthTicketForWebApi(
            nint steamUser,
            [MarshalAs(UnmanagedType.LPStr)] string identity);

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        private delegate void SteamCancelAuthTicket(nint steamUser, uint ticketHandle);
    }
}
