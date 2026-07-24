using System.Drawing.Drawing2D;

namespace SolomonDarkLauncherUpdater;

internal sealed class UpdateProgressBar : Control
{
    private double value_;

    public UpdateProgressBar()
    {
        SetStyle(
            ControlStyles.AllPaintingInWmPaint |
            ControlStyles.OptimizedDoubleBuffer |
            ControlStyles.ResizeRedraw |
            ControlStyles.UserPaint,
            true);
        AccessibleName = "Update progress";
        AccessibleRole = AccessibleRole.ProgressBar;
        BackColor = Color.FromArgb(19, 17, 24);
        ForeColor = Color.FromArgb(199, 164, 78);
        Height = 12;
    }

    public double Value
    {
        get => value_;
        set
        {
            value_ = Math.Clamp(value, 0.0, 100.0);
            AccessibilityNotifyClients(
                AccessibleEvents.ValueChange,
                childID: -1);
            Invalidate();
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;

        var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
        using var trackPath = RoundedRectangle(bounds, 5);
        using var background = new SolidBrush(BackColor);
        using var border = new Pen(Color.FromArgb(58, 52, 72));
        e.Graphics.FillPath(background, trackPath);
        e.Graphics.DrawPath(border, trackPath);

        var fillWidth = (int)Math.Round((Width - 2) * Value / 100.0);
        if (fillWidth <= 0)
        {
            return;
        }

        var fillBounds = new Rectangle(1, 1, fillWidth, Math.Max(1, Height - 3));
        using var fillPath = RoundedRectangle(fillBounds, 4);
        using var fill = new SolidBrush(ForeColor);
        e.Graphics.FillPath(fill, fillPath);
    }

    private static GraphicsPath RoundedRectangle(Rectangle bounds, int radius)
    {
        var diameter = Math.Min(radius * 2, Math.Min(bounds.Width, bounds.Height));
        var path = new GraphicsPath();
        if (diameter <= 0)
        {
            path.AddRectangle(bounds);
            return path;
        }

        var arc = new Rectangle(bounds.Location, new Size(diameter, diameter));
        path.AddArc(arc, 180, 90);
        arc.X = bounds.Right - diameter;
        path.AddArc(arc, 270, 90);
        arc.Y = bounds.Bottom - diameter;
        path.AddArc(arc, 0, 90);
        arc.X = bounds.Left;
        path.AddArc(arc, 90, 90);
        path.CloseFigure();
        return path;
    }
}
