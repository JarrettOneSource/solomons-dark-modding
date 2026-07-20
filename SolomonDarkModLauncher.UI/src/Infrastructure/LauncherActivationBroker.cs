using System.IO.Pipes;

namespace SolomonDarkModLauncher.UI.Infrastructure;

internal sealed class LauncherActivationBroker : IDisposable
{
    private const string MutexName = @"Local\SolomonDarkMultiplayerBeta";
    private const string PipeName = "SolomonDarkMultiplayerBeta.Activation";
    private readonly Mutex mutex_;
    private readonly bool ownsMutex_;
    private readonly CancellationTokenSource cancellation_ = new();
    private Task? listener_;

    public LauncherActivationBroker()
    {
        mutex_ = new Mutex(initiallyOwned: true, MutexName, out ownsMutex_);
    }

    public bool IsPrimary => ownsMutex_;

    public void StartListening(Action<string> activate)
    {
        if (!ownsMutex_ || listener_ is not null)
        {
            throw new InvalidOperationException(
                "Only the primary launcher can start the activation listener.");
        }

        listener_ = ListenAsync(activate, cancellation_.Token);
    }

    public bool ForwardActivation(string argument)
    {
        if (ownsMutex_)
        {
            throw new InvalidOperationException(
                "The primary launcher cannot forward activation to itself.");
        }

        try
        {
            using var client = new NamedPipeClientStream(
                ".",
                PipeName,
                PipeDirection.Out,
                PipeOptions.Asynchronous);
            client.Connect(5000);
            using var writer = new StreamWriter(client) { AutoFlush = true };
            writer.WriteLine(argument);
            return true;
        }
        catch (IOException)
        {
            return false;
        }
        catch (TimeoutException)
        {
            return false;
        }
    }

    private static async Task ListenAsync(
        Action<string> activate,
        CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await using var server = new NamedPipeServerStream(
                    PipeName,
                    PipeDirection.In,
                    1,
                    PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous);
                await server.WaitForConnectionAsync(cancellationToken);
                using var reader = new StreamReader(server);
                var argument = await reader.ReadLineAsync(cancellationToken);
                if (argument is not null)
                {
                    activate(argument);
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                return;
            }
            catch (IOException) when (!cancellationToken.IsCancellationRequested)
            {
            }
        }
    }

    public void Dispose()
    {
        cancellation_.Cancel();
        if (ownsMutex_)
        {
            mutex_.ReleaseMutex();
        }
        mutex_.Dispose();
        cancellation_.Dispose();
    }
}
