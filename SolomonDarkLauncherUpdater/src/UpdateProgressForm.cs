using System.Runtime.InteropServices;
using SolomonDarkModding.Updates;

namespace SolomonDarkLauncherUpdater;

internal sealed class UpdateProgressForm : Form
{
    private static readonly Color WindowBackground = Color.FromArgb(23, 21, 28);
    private static readonly Color TitleBarBackground = Color.FromArgb(16, 14, 20);
    private static readonly Color GoldOutline = Color.FromArgb(121, 100, 58);
    private static readonly Color GoldOutlineText = Color.FromArgb(214, 188, 124);
    private static readonly Color GoldOutlineHover = Color.FromArgb(43, 36, 22);
    private static readonly Color BorderSubtle = Color.FromArgb(50, 45, 61);
    private static readonly Color Accent = Color.FromArgb(199, 164, 78);
    private static readonly Color AccentHover = Color.FromArgb(219, 186, 102);
    private static readonly Color AccentPressed = Color.FromArgb(165, 133, 60);
    private static readonly Color AccentText = Color.FromArgb(30, 22, 8);
    private static readonly Color TextPrimary = Color.FromArgb(237, 232, 220);
    private static readonly Color TextSecondary = Color.FromArgb(168, 160, 147);
    private static readonly Color TextMuted = Color.FromArgb(111, 106, 97);
    private static readonly Color Success = Color.FromArgb(79, 193, 166);
    private static readonly Color Error = Color.FromArgb(224, 106, 87);

    private const int WmNcLButtonDown = 0x00A1;
    private const int HtCaption = 0x2;

    private readonly Label statusLabel_;
    private readonly Label completeGlyph_;
    private readonly Label detailLabel_;
    private readonly UpdateProgressBar progressBar_;
    private readonly FlowLayoutPanel actions_;
    private readonly Button restartButton_;
    private readonly Button closeButton_;
    private readonly Button closeGlyph_;
    private bool canClose_;

    public UpdateProgressForm()
    {
        Text = "Solomon Dark Revived Update";
        AccessibleName = Text;
        BackColor = WindowBackground;
        ForeColor = TextPrimary;
        ClientSize = new Size(560, 210);
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.CenterScreen;

        var titleBar = new Panel
        {
            BackColor = TitleBarBackground,
            Location = new Point(1, 1),
            Size = new Size(558, 42),
            Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        };
        titleBar.MouseDown += DragWindow;
        Controls.Add(titleBar);

        var brandGlyph = new Label
        {
            AutoSize = true,
            BackColor = Color.Transparent,
            Font = new Font("Segoe UI", 9f),
            ForeColor = Accent,
            Location = new Point(16, 13),
            Text = "◆"
        };
        brandGlyph.MouseDown += DragWindow;
        titleBar.Controls.Add(brandGlyph);

        var titleLabel = new Label
        {
            AutoSize = true,
            BackColor = Color.Transparent,
            Font = new Font("Segoe UI Semibold", 9.5f),
            ForeColor = TextPrimary,
            Location = new Point(38, 12),
            Text = "Solomon Dark Revived Update"
        };
        titleLabel.MouseDown += DragWindow;
        titleBar.Controls.Add(titleLabel);

        closeGlyph_ = new Button
        {
            Anchor = AnchorStyles.Top | AnchorStyles.Right,
            BackColor = TitleBarBackground,
            FlatStyle = FlatStyle.Flat,
            Font = new Font("Segoe UI", 10f),
            ForeColor = TextMuted,
            Location = new Point(512, 0),
            Size = new Size(46, 42),
            TabStop = false,
            Text = "✕",
            UseVisualStyleBackColor = false
        };
        closeGlyph_.FlatAppearance.BorderSize = 0;
        closeGlyph_.FlatAppearance.MouseOverBackColor = Color.FromArgb(196, 43, 28);
        closeGlyph_.FlatAppearance.MouseDownBackColor = Color.FromArgb(178, 42, 26);
        closeGlyph_.Click += (_, _) =>
        {
            if (canClose_)
            {
                Close();
            }
        };
        titleBar.Controls.Add(closeGlyph_);

        completeGlyph_ = new Label
        {
            AutoSize = true,
            Font = new Font("Segoe UI", 12.5f, FontStyle.Bold),
            ForeColor = Success,
            Location = new Point(24, 58),
            Text = "✓",
            Visible = false
        };
        Controls.Add(completeGlyph_);

        statusLabel_ = new Label
        {
            AutoEllipsis = true,
            Font = new Font("Segoe UI Semibold", 12.5f),
            ForeColor = TextPrimary,
            Location = new Point(24, 58),
            Size = new Size(512, 28),
            Text = "Preparing launcher update…"
        };
        Controls.Add(statusLabel_);

        detailLabel_ = new Label
        {
            AutoEllipsis = true,
            Font = new Font("Segoe UI", 9.5f),
            ForeColor = TextSecondary,
            Location = new Point(24, 90),
            Size = new Size(512, 20),
            Text = "The launcher will restart automatically."
        };
        Controls.Add(detailLabel_);

        progressBar_ = new UpdateProgressBar
        {
            Location = new Point(24, 122),
            Size = new Size(512, 14)
        };
        Controls.Add(progressBar_);

        actions_ = new FlowLayoutPanel
        {
            AutoSize = false,
            FlowDirection = FlowDirection.RightToLeft,
            Location = new Point(24, 154),
            Size = new Size(512, 40),
            Visible = false,
            WrapContents = false
        };
        Controls.Add(actions_);

        closeButton_ = CreateButton("Close", primary: false);
        closeButton_.Click += (_, _) =>
        {
            canClose_ = true;
            Close();
        };
        actions_.Controls.Add(closeButton_);

        restartButton_ = CreateButton("Restart Launcher", primary: true);
        actions_.Controls.Add(restartButton_);

        FormClosing += (_, eventArgs) =>
        {
            if (!canClose_)
            {
                eventArgs.Cancel = true;
            }
        };
    }

    public int ExitCode { get; private set; } = 1;

    public void Report(UpdateProgress progress)
    {
        statusLabel_.Text = progress.StatusText;
        detailLabel_.ForeColor = TextSecondary;
        detailLabel_.Text = FormatDetail(progress);

        var value = CalculateValue(progress);
        progressBar_.Value = value;
        progressBar_.Indeterminate =
            progress.Phase is not
                (UpdateProgressPhase.Completed or UpdateProgressPhase.Failed) &&
            value <= 0;
        progressBar_.ForeColor =
            progress.Phase == UpdateProgressPhase.Failed ? Error : Accent;

        var complete = progress.Phase == UpdateProgressPhase.Completed;
        completeGlyph_.Visible = complete;
        statusLabel_.Location = new Point(complete ? 48 : 24, statusLabel_.Top);
        statusLabel_.Width = complete ? 488 : 512;
        statusLabel_.ForeColor =
            progress.Phase == UpdateProgressPhase.Failed ? Error : TextPrimary;
    }

    public void ShowFailure(string message, Action restart)
    {
        Report(new UpdateProgress(
            UpdateProgressPhase.Failed,
            "The launcher update failed."));
        detailLabel_.ForeColor = Error;
        detailLabel_.Text = message.ReplaceLineEndings(" ");
        restartButton_.Click += (_, _) =>
        {
            try
            {
                restart();
                canClose_ = true;
                Close();
            }
            catch (Exception exception)
            {
                detailLabel_.Text =
                    $"The launcher could not restart: {exception.Message}";
            }
        };
        actions_.Visible = true;
        canClose_ = true;
        closeGlyph_.ForeColor = TextSecondary;
    }

    public void CloseAfterSuccess()
    {
        ExitCode = 0;
        canClose_ = true;
        closeGlyph_.ForeColor = TextSecondary;
        Close();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        using var border = new Pen(GoldOutline);
        e.Graphics.DrawRectangle(border, 0, 0, Width - 1, Height - 1);
        using var divider = new Pen(BorderSubtle);
        e.Graphics.DrawLine(divider, 1, 43, Width - 2, 43);
    }

    private void DragWindow(object? sender, MouseEventArgs e)
    {
        if (e.Button != MouseButtons.Left)
        {
            return;
        }
        ReleaseCapture();
        _ = SendMessage(Handle, WmNcLButtonDown, (IntPtr)HtCaption, IntPtr.Zero);
    }

    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(
        IntPtr hWnd,
        int msg,
        IntPtr wParam,
        IntPtr lParam);

    private static Button CreateButton(string text, bool primary)
    {
        var button = new Button
        {
            AutoSize = true,
            BackColor = primary ? Accent : WindowBackground,
            FlatStyle = FlatStyle.Flat,
            Font = new Font("Segoe UI", 9f, FontStyle.Bold),
            ForeColor = primary ? AccentText : GoldOutlineText,
            Margin = new Padding(10, 4, 0, 4),
            Padding = new Padding(12, 5, 12, 5),
            Text = text,
            UseVisualStyleBackColor = false
        };
        button.FlatAppearance.BorderSize = primary ? 0 : 1;
        button.FlatAppearance.BorderColor = GoldOutline;
        button.FlatAppearance.MouseOverBackColor =
            primary ? AccentHover : GoldOutlineHover;
        button.FlatAppearance.MouseDownBackColor =
            primary ? AccentPressed : GoldOutlineHover;
        return button;
    }

    private static double CalculateValue(UpdateProgress progress)
    {
        if (progress.Phase == UpdateProgressPhase.Completed)
        {
            return 100;
        }
        return progress.Completed is { } completed &&
               progress.Total is > 0 and var total
            ? Math.Clamp(completed * 100.0 / total, 0.0, 100.0)
            : 0;
    }

    private static string FormatDetail(UpdateProgress progress)
    {
        if (progress.Completed is not { } completed)
        {
            return progress.Phase == UpdateProgressPhase.Restarting
                ? "Installation finished successfully."
                : string.Empty;
        }
        if (progress.Total is not (> 0 and var total))
        {
            return progress.Unit == UpdateProgressUnit.Bytes
                ? FormatSize(completed)
                : string.Empty;
        }

        var percentage = Math.Clamp(completed * 100.0 / total, 0.0, 100.0);
        return progress.Unit switch
        {
            UpdateProgressUnit.Bytes =>
                $"{percentage:0}% · {FormatSize(completed)} of {FormatSize(total)}",
            UpdateProgressUnit.Items => $"{percentage:0}% · {completed} of {total}",
            _ => $"{percentage:0}%"
        };
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1024L * 1024L * 1024L => $"{bytes / (1024.0 * 1024.0 * 1024.0):0.##} GB",
        >= 1024L * 1024L => $"{bytes / (1024.0 * 1024.0):0.##} MB",
        >= 1024L => $"{bytes / 1024.0:0.##} KB",
        _ => $"{bytes} bytes"
    };
}
