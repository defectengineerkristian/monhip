using System;
using System.Drawing;
using System.Windows.Forms;

namespace MonhipInstaller
{
	public class BaseForm : Form
	{
		protected const int ContentWidth = 560;

		protected readonly Label TitleLabel;

		protected readonly Label SubLabel;

		protected readonly FlowLayoutPanel Body;

		protected readonly FlowLayoutPanel Footer;

		public BaseForm(string caption, int width, int height)
		{
			Text = caption;
			Font = Theme.Base;
			BackColor = Theme.P.Bg;
			ForeColor = Theme.P.Fg;
			base.FormBorderStyle = FormBorderStyle.FixedSingle;
			base.MaximizeBox = false;
			base.StartPosition = FormStartPosition.CenterScreen;
			base.AutoScaleMode = AutoScaleMode.None;
			base.ClientSize = new Size(Theme.S(width), Theme.S(height));
			try
			{
				base.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
			}
			catch (Exception)
			{
			}
			Body = new FlowLayoutPanel
			{
				Dock = DockStyle.Fill,
				FlowDirection = FlowDirection.TopDown,
				WrapContents = false,
				AutoScroll = true,
				Padding = new Padding(Theme.S(28), Theme.S(4), Theme.S(20), 0)
			};
			Footer = new FlowLayoutPanel
			{
				Dock = DockStyle.Bottom,
				FlowDirection = FlowDirection.RightToLeft,
				Height = Theme.S(64),
				Padding = new Padding(Theme.S(20), Theme.S(14), Theme.S(20), 0),
				BackColor = (Theme.P.Dark ? ColorTranslator.FromHtml("#1f1e1d") : Theme.P.Surface)
			};
			Panel panel = new Panel
			{
				Dock = DockStyle.Top,
				Height = Theme.S(84),
				Padding = new Padding(Theme.S(28), Theme.S(18), Theme.S(20), 0)
			};
			TitleLabel = new Label
			{
				AutoSize = true,
				Font = Theme.Title,
				ForeColor = Theme.P.Fg,
				Location = new Point(Theme.S(26), Theme.S(16))
			};
			SubLabel = new Label
			{
				AutoSize = true,
				Font = Theme.Base,
				ForeColor = Theme.P.Muted,
				Location = new Point(Theme.S(28), Theme.S(52)),
				MaximumSize = new Size(Theme.S(width - 56), 0)
			};
			panel.Controls.Add(TitleLabel);
			panel.Controls.Add(SubLabel);
			base.Controls.Add(Body);
			base.Controls.Add(Footer);
			base.Controls.Add(panel);
		}

		protected override void OnHandleCreated(EventArgs e)
		{
			base.OnHandleCreated(e);
			Theme.TitleBar(this);
		}

		protected void Page(string title, string sub)
		{
			TitleLabel.Text = title;
			SubLabel.Text = sub;
			Body.Controls.Clear();
			Footer.Controls.Clear();
		}

		protected Button AddButton(string text, bool accent, EventHandler click)
		{
			Button button = Theme.Button(text, accent);
			button.Click += click;
			Footer.Controls.Add(button);
			if (accent)
			{
				base.AcceptButton = button;
			}
			return button;
		}

		public void Ui(Action a)
		{
			if (base.IsDisposed)
			{
				return;
			}
			try
			{
				BeginInvoke(a);
			}
			catch (InvalidOperationException)
			{
			}
		}
	}
}
