using Microsoft.Win32.SafeHandles;

namespace SolomonDarkModLauncher.Native;

internal sealed class SafeKernelObjectHandle : SafeHandleZeroOrMinusOneIsInvalid
{
    public SafeKernelObjectHandle()
        : base(ownsHandle: true)
    {
    }

    protected override bool ReleaseHandle()
    {
        return Kernel32.CloseHandle(handle);
    }
}
