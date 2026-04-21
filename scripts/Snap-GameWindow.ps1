Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string c, string t);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int nCmdShow);
    [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder t, int n);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc e, IntPtr p);
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@ -ReferencedAssemblies System.Drawing

Add-Type -AssemblyName System.Drawing

$found = $null
$cb = [W+EnumProc]{ param($h,$p)
    $len = [W]::GetWindowTextLength($h)
    if ($len -gt 0) {
        $sb = New-Object System.Text.StringBuilder ($len+1)
        [void][W]::GetWindowText($h,$sb,$sb.Capacity)
        $t = $sb.ToString()
        if ($t -match "Solomon") {
            $script:found = [PSCustomObject]@{ H = $h; T = $t }
            return $false
        }
    }
    return $true
}
[void][W]::EnumWindows($cb, [IntPtr]::Zero)
if (-not $found) { Write-Output "NOT FOUND"; exit 1 }
Write-Output ("Found: " + $found.T + " hwnd=" + $found.H)
$h = $found.H
if ([W]::IsIconic($h)) { [void][W]::ShowWindow($h, 9) }
Start-Sleep -Milliseconds 300
$r = New-Object W+RECT
[void][W]::GetClientRect($h, [ref]$r)
$w = $r.R - $r.L; $hgt = $r.B - $r.T
Write-Output ("client size: " + $w + "x" + $hgt)
$bmp = New-Object System.Drawing.Bitmap $w, $hgt
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[void][W]::PrintWindow($h, $hdc, 1)
$g.ReleaseHdc($hdc)
$path = "C:\Users\User\Documents\GitHub\SB Modding\Solomon Dark\Mod Loader\runtime\stage\.sdmod\logs\diag-game.png"
$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output $path
