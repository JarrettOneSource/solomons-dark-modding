using System.Drawing.Drawing2D;

namespace SolomonDarkLauncherUpdater;

internal sealed class UpdateProgressBar : Control
{
    private static readonly Color TrackColor = Color.FromArgb(19, 17, 24);
    private static readonly Color TrackBorderColor = Color.FromArgb(58, 52, 72);
    private static readonly Color GoldDark = Color.FromArgb(165, 133, 60);
    private static readonly Color Gold = Color.FromArgb(199, 164, 78);
    private static readonly Color GoldLight = Color.FromArgb(219, 186, 102);

    private readonly System.Windows.Forms.Timer animation_;
    private double value_;
    private bool indeterminate_;
    private float sweep_ = -160f;

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
        BackColor = TrackColor;
        ForeColor = Gold;
        Height = 14;
        animation_ = new System.Windows.Forms.Timer { Interval = 33 };
        animation_.Tick += (_, _) => AdvanceSweep();
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
            UpdateAnimationState();
            Invalidate();
        }
    }

    public bool Indeterminate
    {
        get => indeterminate_;
        set
        {
            if (indeterminate_ == value)
            {
                return;
            }
            indeterminate_ = value;
            UpdateAnimationState();
            Invalidate();
        }
    }

    protected override void OnVisibleChanged(EventArgs e)
    {
        base.OnVisibleChanged(e);
        UpdateAnimationState();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            animation_.Dispose();
        }
        base.Dispose(disposing);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;

        var track = new Rectangle(0, 0, Width - 1, Height - 1);
        var radius = Math.Max(3, (Height - 1) / 2 - 1);
        using (var trackPath = RoundedRectangle(track, radius))
        using (var trackFill = new SolidBrush(TrackColor))
        using (var trackBorder = new Pen(TrackBorderColor))
        {
            e.Graphics.FillPath(trackFill, trackPath);
            e.Graphics.DrawPath(trackBorder, trackPath);
        }

        if (indeterminate_)
        {
            PaintMarquee(e.Graphics, radius);
            return;
        }

        var fillWidth = (int)Math.Round((Width - 2) * value_ / 100.0);
        if (fillWidth <= 0)
        {
            return;
        }

        var fill = new Rectangle(1, 1, fillWidth, Math.Max(1, Height - 3));
        var goldFill = ForeColor.ToArgb() == Gold.ToArgb();
        using var fillPath = RoundedRectangle(fill, Math.Max(2, radius - 1));

        using (var glow = new Pen(
            Color.FromArgb(70, goldFill ? Gold : ForeColor),
            3f))
        {
            e.Graphics.DrawPath(glow, fillPath);
        }

        if (goldFill)
        {
            using var gradient = new LinearGradientBrush(
                new Rectangle(fill.X, fill.Y, Math.Max(2, fill.Width), fill.Height),
                GoldDark,
                GoldLight,
                LinearGradientMode.Horizontal);
            gradient.InterpolationColors = new ColorBlend
            {
                Colors = new[] { GoldDark, Gold, GoldLight },
                Positions = new[] { 0f, 0.55f, 1f }
            };
            e.Graphics.FillPath(gradient, fillPath);
        }
        else
        {
            using var solid = new SolidBrush(ForeColor);
            e.Graphics.FillPath(solid, fillPath);
        }

        using (var highlight = new Pen(Color.FromArgb(45, 255, 255, 255)))
        {
            var inset = Math.Max(2, radius - 1);
            e.Graphics.DrawLine(
                highlight,
                fill.X + inset,
                fill.Y + 1,
                Math.Max(fill.X + inset, fill.Right - inset),
                fill.Y + 1);
        }

        if (animation_.Enabled && fillWidth > 90)
        {
            PaintSheen(e.Graphics, fillPath, fill);
        }
    }

    private void PaintMarquee(Graphics graphics, int radius)
    {
        var band = Math.Max(90f, Width / 4f);
        var bounds = new RectangleF(sweep_, 1, band, Math.Max(1, Height - 3));
        using var clip = RoundedRectangle(
            new Rectangle(1, 1, Width - 3, Math.Max(1, Height - 3)),
            Math.Max(2, radius - 1));
        using var gradient = new LinearGradientBrush(
            new RectangleF(bounds.X - 1, bounds.Y, bounds.Width + 2, bounds.Height),
            Color.FromArgb(0, Gold),
            Color.FromArgb(0, Gold),
            LinearGradientMode.Horizontal);
        gradient.InterpolationColors = new ColorBlend
        {
            Colors = new[]
            {
                Color.FromArgb(0, Gold),
                Color.FromArgb(200, Gold),
                Color.FromArgb(0, Gold)
            },
            Positions = new[] { 0f, 0.5f, 1f }
        };
        var state = graphics.Save();
        graphics.SetClip(clip);
        graphics.FillRectangle(gradient, bounds);
        graphics.Restore(state);
    }

    private void PaintSheen(Graphics graphics, GraphicsPath fillPath, Rectangle fill)
    {
        var bounds = new RectangleF(sweep_, fill.Y, 70, fill.Height);
        if (bounds.Right < fill.X || bounds.X > fill.Right)
        {
            return;
        }
        using var gradient = new LinearGradientBrush(
            new RectangleF(bounds.X - 1, bounds.Y, bounds.Width + 2, bounds.Height),
            Color.FromArgb(0, 255, 255, 255),
            Color.FromArgb(0, 255, 255, 255),
            LinearGradientMode.Horizontal);
        gradient.InterpolationColors = new ColorBlend
        {
            Colors = new[]
            {
                Color.FromArgb(0, 255, 255, 255),
                Color.FromArgb(40, 255, 255, 255),
                Color.FromArgb(0, 255, 255, 255)
            },
            Positions = new[] { 0f, 0.5f, 1f }
        };
        var state = graphics.Save();
        graphics.SetClip(fillPath);
        graphics.FillRectangle(gradient, bounds);
        graphics.Restore(state);
    }

    private void AdvanceSweep()
    {
        sweep_ += indeterminate_ ? 6f : 4f;
        if (sweep_ > Width + 160f)
        {
            sweep_ = -160f;
        }
        Invalidate();
    }

    private void UpdateAnimationState()
    {
        var animate = Visible &&
            (indeterminate_ || (value_ > 0.0 && value_ < 100.0));
        if (animate == animation_.Enabled)
        {
            return;
        }
        if (animate)
        {
            sweep_ = -160f;
            animation_.Start();
        }
        else
        {
            animation_.Stop();
        }
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
