using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace MonhipInstaller
{
	public class Bar : Control
	{
		private double value = -1.0;

		private int phase;

		private readonly Timer timer = new Timer
		{
			Interval = 30
		};

		public double Value
		{
			get
			{
				return value;
			}
			set
			{
				this.value = value;
				timer.Enabled = value < 0.0 && base.Visible;
				Invalidate();
			}
		}

		public Bar()
		{
			SetStyle(ControlStyles.UserPaint | ControlStyles.ResizeRedraw | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
			base.Height = Theme.S(6);
			base.Margin = new Padding(0, Theme.S(10), 0, Theme.S(6));
			Timer obj = timer;
			EventHandler eventHandler = delegate
			{
				phase = (phase + 3) % 200;
				Invalidate();
			};
			obj.Tick += eventHandler;
		}

		protected override void OnVisibleChanged(EventArgs e)
		{
			base.OnVisibleChanged(e);
			timer.Enabled = value < 0.0 && base.Visible;
		}

		protected override void OnPaint(PaintEventArgs e)
		{
			Graphics graphics = e.Graphics;
			graphics.SmoothingMode = SmoothingMode.AntiAlias;
			graphics.Clear((base.Parent != null) ? base.Parent.BackColor : Theme.P.Bg);
			using (SolidBrush b = new SolidBrush(Theme.P.Raised))
			{
				Pill(graphics, b, 0, base.Width);
			}
			using (SolidBrush b2 = new SolidBrush(Theme.P.Accent))
			{
				if (value >= 0.0)
				{
					Pill(graphics, b2, 0, (int)((double)base.Width * Math.Min(100.0, value) / 100.0));
					return;
				}
				int num = base.Width / 4;
				int num2 = (int)((double)(base.Width + num) * ((double)phase / 200.0)) - num;
				Pill(graphics, b2, Math.Max(0, num2), Math.Min(base.Width, num2 + num) - Math.Max(0, num2));
			}
		}

		private void Pill(Graphics g, Brush b, int x, int w)
		{
			if (w <= 0)
			{
				return;
			}
			int num = base.Height - 1;
			int num2 = Math.Min(num, w);
			using (GraphicsPath graphicsPath = new GraphicsPath())
			{
				graphicsPath.AddArc(x, 0, num2, num, 90f, 180f);
				graphicsPath.AddArc(x + w - num2, 0, num2, num, 270f, 180f);
				graphicsPath.CloseFigure();
				g.FillPath(b, graphicsPath);
			}
		}

		protected override void Dispose(bool disposing)
		{
			if (disposing)
			{
				timer.Dispose();
			}
			base.Dispose(disposing);
		}
	}
}
