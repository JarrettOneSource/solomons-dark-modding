using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using SolomonDarkModLauncher.Native;

namespace SolomonDarkModLauncher.Launch;

internal static class WindowsDllInjector
{
    private const uint InjectionTimeoutMilliseconds = 15000;

    public static void Inject(Process process, string dllPath)
    {
        if (process.HasExited)
        {
            throw new InvalidOperationException("The staged game exited before loader injection could begin.");
        }

        var fullDllPath = Path.GetFullPath(dllPath);
        if (!File.Exists(fullDllPath))
        {
            throw new FileNotFoundException(
                $"The launcher could not find SolomonDarkModLoader.dll next to the launcher executable.",
                fullDllPath);
        }

        TryWaitForInputIdle(process);

        using var processHandle = Kernel32.OpenProcess(Kernel32.ProcessAccess, false, (uint)process.Id);
        if (processHandle.IsInvalid)
        {
            ThrowLastWin32("OpenProcess failed while preparing DLL injection.");
        }

        var kernel32 = Kernel32.GetModuleHandleW("kernel32.dll");
        if (kernel32 == IntPtr.Zero)
        {
            ThrowLastWin32("GetModuleHandleW failed while resolving kernel32.");
        }

        var loadLibraryAddress = Kernel32.GetProcAddress(kernel32, "LoadLibraryW");
        if (loadLibraryAddress == IntPtr.Zero)
        {
            ThrowLastWin32("GetProcAddress failed while resolving LoadLibraryW.");
        }

        var dllPathBytes = Encoding.Unicode.GetBytes(fullDllPath + '\0');
        var remoteDllPath = Kernel32.VirtualAllocEx(
            processHandle,
            IntPtr.Zero,
            (nuint)dllPathBytes.Length,
            Kernel32.MemCommit | Kernel32.MemReserve,
            Kernel32.PageReadWrite);
        if (remoteDllPath == IntPtr.Zero)
        {
            ThrowLastWin32("VirtualAllocEx failed while reserving the remote DLL path buffer.");
        }

        try
        {
            if (!Kernel32.WriteProcessMemory(
                    processHandle,
                    remoteDllPath,
                    dllPathBytes,
                    (nuint)dllPathBytes.Length,
                    out var bytesWritten))
            {
                ThrowLastWin32("WriteProcessMemory failed while copying the remote DLL path.");
            }

            if (bytesWritten != (nuint)dllPathBytes.Length)
            {
                throw new InvalidOperationException(
                    $"WriteProcessMemory copied {bytesWritten} bytes but expected {dllPathBytes.Length}.");
            }

            using var remoteThread = Kernel32.CreateRemoteThread(
                processHandle,
                IntPtr.Zero,
                0,
                loadLibraryAddress,
                remoteDllPath,
                0,
                out _);
            if (remoteThread.IsInvalid)
            {
                ThrowLastWin32("CreateRemoteThread failed while starting remote LoadLibraryW.");
            }

            var waitResult = Kernel32.WaitForSingleObject(remoteThread, InjectionTimeoutMilliseconds);
            if (waitResult == Kernel32.WaitFailed)
            {
                ThrowLastWin32("WaitForSingleObject failed while waiting for remote LoadLibraryW.");
            }

            if (waitResult == Kernel32.WaitTimeout)
            {
                throw new InvalidOperationException("Remote LoadLibraryW timed out after 15 seconds.");
            }

            if (waitResult != Kernel32.WaitObject0)
            {
                throw new InvalidOperationException(
                    $"Unexpected wait result while injecting SolomonDarkModLoader.dll: 0x{waitResult:X8}.");
            }

            if (!Kernel32.GetExitCodeThread(remoteThread, out var remoteModuleHandle))
            {
                ThrowLastWin32("GetExitCodeThread failed after remote LoadLibraryW completed.");
            }

            if (remoteModuleHandle == 0)
            {
                throw new InvalidOperationException(
                    "Remote LoadLibraryW returned null. SolomonDarkModLoader.dll was not loaded into the target process.");
            }
        }
        finally
        {
            Kernel32.VirtualFreeEx(processHandle, remoteDllPath, 0, Kernel32.MemRelease);
        }
    }

    private static void TryWaitForInputIdle(Process process)
    {
        try
        {
            process.WaitForInputIdle(5000);
        }
        catch (InvalidOperationException)
        {
            if (process.HasExited)
            {
                throw new InvalidOperationException("The staged game exited before the loader could be injected.");
            }
        }
    }

    private static void ThrowLastWin32(string message)
    {
        var errorCode = Marshal.GetLastWin32Error();
        var systemMessage = new Win32Exception(errorCode).Message;
        throw new Win32Exception(errorCode, $"{message} Win32={errorCode} ({systemMessage})");
    }
}
