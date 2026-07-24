using SolomonDarkModding.Updates;

namespace SolomonDarkLauncherUpdater;

internal sealed class UpdateProgressForm : Form
{
    private static readonly Color WindowBackground = Color.FromArgb(23, 21, 28);
    private static readonly Color CardBackground = Color.FromArgb(33, 30, 40);
    private static readonly Color Accent = Color.FromArgb(199, 164, 78);
    private static readonly Color TextPrimary = Color.FromArgb(237, 232, 220);
    private static readonly Color TextSecondary = Color.FromArgb(168, 160, 147);
    private static readonly Color TextMuted = Color.FromArgb(111, 106, 97);
    private static readonly Color Success = Color.FromArgb(79, 193, 166);
    private static readonly Color Error = Color.FromArgb(224, 106, 87);

    private readonly Label statusLabel_;
    private readonly Label detailLabel_;
    private readonly UpdateProgressBar progressBar_;
    private readonly FlowLayoutPanel actions_;
    private readonly Button restartButton_;
    private readonly Button closeButton_;
    private bool canClose_;

    public UpdateProgressForm()
    {
        Text = "Solomon Dark Revived Update";
        AccessibleName = Text;
        BackColor = WindowBackground;
        ForeColor = TextPrimary;
        ClientSize = new Size(540, 230);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;

        var card = new Panel
        {
            BackColor = CardBackground,
            Location = new Point(24, 22),
            Size = new Size(492, 184),
            Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right
        };
        Controls.Add(card);

        var heading = new Label
        {
            AutoSize = true,
            Font = new Font("Segoe UI", 9, FontStyle.Bold),
            ForeColor = Accent,
            Location = new Point(22, 18),
            Text = "SOLOMON DARK REVIVED"
        };
        card.Controls.Add(heading);

        statusLabel_ = new Label
        {
            AutoEllipsis = true,
            Font = new Font("Segoe UI", 12, FontStyle.Bold),
            ForeColor = TextPrimary,
            Location = new Point(22, 48),
            Size = new Size(448, 26),
            Text = "Preparing launcher update…"
        };
        card.Controls.Add(statusLabel_);

        detailLabel_ = new Label
        {
            AutoEllipsis = true,
            Font = new Font("Segoe UI", 9),
            ForeColor = TextMuted,
            Location = new Point(22, 78),
            Size = new Size(448, 36),
            Text = "The launcher will restart automatically."
        };
        card.Controls.Add(detailLabel_);

        progressBar_ = new UpdateProgressBar
        {
            Location = new Point(22, 116),
            Size = new Size(448, 12)
        };
        card.Controls.Add(progressBar_);

        actions_ = new FlowLayoutPanel
        {
            AutoSize = true,
            FlowDirection = FlowDirection.RightToLeft,
            Location = new Point(236, 139),
            Size = new Size(234, 34),
            Visible = false,
            WrapContents = false
        };
        card.Controls.Add(actions_);

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
        detailLabel_.Text = FormatDetail(progress);
        progressBar_.Value = CalculateValue(progress);
        progressBar_.ForeColor = progress.Phase switch
        {
            UpdateProgressPhase.Completed => Success,
            UpdateProgressPhase.Failed => Error,
            _ => Accent
        };
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
    }

    public void CloseAfterSuccess()
    {
        ExitCode = 0;
        canClose_ = true;
        Close();
    }

    private static Button CreateButton(string text, bool primary)
    {
        var button = new Button
        {
            AutoSize = true,
            BackColor = primary ? Accent : Color.FromArgb(46, 41, 56),
            FlatStyle = FlatStyle.Flat,
            Font = new Font("Segoe UI", 9, FontStyle.Bold),
            ForeColor = primary ? Color.FromArgb(30, 22, 8) : TextSecondary,
            Margin = new Padding(8, 0, 0, 0),
            Padding = new Padding(10, 3, 10, 3),
            Text = text,
            UseVisualStyleBackColor = false
        };
        button.FlatAppearance.BorderSize = 0;
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
