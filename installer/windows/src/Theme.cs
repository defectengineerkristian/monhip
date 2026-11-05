using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

namespace MonhipInstaller
{
	public static class Theme
	{
		public static Palette P;

		public static float Scale = 1f;

		public static Font Base;

		public static Font Small;

		public static Font Bold;

		public static Font Title;

		private static Color C(string hex)
		{
			return ColorTranslator.FromHtml(hex);
		}

		public static void Init(string installDir)
		{
			using (Graphics graphics = Graphics.FromHwnd(IntPtr.Zero))
			{
				Scale = graphics.DpiX / 96f;
			}
			string text = "";
			try
			{
				string text2 = ((installDir == null) ? null : Path.Combine(installDir, "config.json"));
				if (text2 != null && File.Exists(text2))
				{
					text = Json.Str(Json.Parse(File.ReadAllText(text2, Encoding.UTF8)), "theme");
				}
			}
			catch (Exception)
			{
			}
			Palette p;
			if (!(text == "dark") && (!(text != "light") || WindowsLight()))
			{
				Palette palette = new Palette();
				palette.Dark = false;
				palette.Bg = C("#ffffff");
				palette.Surface = C("#f5f2fe");
				palette.Raised = C("#efeafc");
				palette.Fg = C("#1f1b2d");
				palette.Muted = C("#6c6784");
				palette.Accent = C("#7c3aed");
				palette.AccentFg = C("#ffffff");
				palette.AccentHover = C("#6d28d9");
				palette.Border = C("#dcd4f1");
				palette.Error = C("#c81e1e");
				palette.Ok = C("#2f8a4c");
				p = palette;
			}
			else
			{
				Palette palette2 = new Palette();
				palette2.Dark = true;
				palette2.Bg = C("#262624");
				palette2.Surface = C("#30302e");
				palette2.Raised = C("#3b3a36");
				palette2.Fg = C("#ece9e1");
				palette2.Muted = C("#9d998e");
				palette2.Accent = C("#d97757");
				palette2.AccentFg = C("#1f1e1d");
				palette2.AccentHover = C("#e3896a");
				palette2.Border = C("#45433e");
				palette2.Error = C("#ff7b72");
				palette2.Ok = C("#7ec699");
				p = palette2;
			}
			P = p;
			Base = new Font("Segoe UI", 9.75f);
			Small = new Font("Segoe UI", 9f);
			Bold = new Font("Segoe UI Semibold", 9.75f);
			Title = new Font("Segoe UI Semibold", 15f);
		}

		private static bool WindowsLight()
		{
			try
			{
				using (RegistryKey registryKey = Registry.CurrentUser.OpenSubKey("Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize"))
				{
					return registryKey != null && Convert.ToInt32(registryKey.GetValue("AppsUseLightTheme", 1)) != 0;
				}
			}
			catch (Exception)
			{
				return true;
			}
		}

		public static int S(int px)
		{
			return (int)Math.Round((float)px * Scale);
		}

		[DllImport("dwmapi.dll")]
		private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

		public static void TitleBar(Form f)
		{
			try
			{
				int value = (P.Dark ? 1 : 0);
				DwmSetWindowAttribute(f.Handle, 20, ref value, 4);
				int value2 = ColorTranslator.ToWin32(P.Bg);
				int value3 = ColorTranslator.ToWin32(P.Fg);
				DwmSetWindowAttribute(f.Handle, 35, ref value2, 4);
				DwmSetWindowAttribute(f.Handle, 36, ref value3, 4);
			}
			catch (Exception)
			{
			}
		}

		public static Label Text(string text, bool muted, int width)
		{
			Label label = new Label();
			label.Text = text;
			label.AutoSize = true;
			label.ForeColor = (muted ? P.Muted : P.Fg);
			label.Font = (muted ? Small : Base);
			label.Margin = new Padding(0, 0, 0, S(6));
			Label label2 = label;
			if (width > 0)
			{
				label2.MaximumSize = new Size(S(width), 0);
			}
			return label2;
		}

		public static Label Heading(string text)
		{
			Label label = new Label();
			label.Text = text;
			label.AutoSize = true;
			label.ForeColor = P.Fg;
			label.Font = Bold;
			label.Margin = new Padding(0, S(8), 0, S(2));
			return label;
		}

		public static Button Button(string text, bool accent)
		{
			Button button = new Button();
			button.Text = text;
			button.AutoSize = true;
			button.FlatStyle = FlatStyle.Flat;
			button.Cursor = Cursors.Hand;
			button.BackColor = (accent ? P.Accent : P.Raised);
			button.ForeColor = (accent ? P.AccentFg : P.Fg);
			button.Font = (accent ? Bold : Base);
			button.MinimumSize = new Size(S(112), S(34));
			button.Padding = new Padding(S(10), 0, S(10), 0);
			button.Margin = new Padding(S(6), 0, 0, 0);
			button.UseVisualStyleBackColor = false;
			Button button2 = button;
			button2.FlatAppearance.BorderSize = ((!accent) ? 1 : 0);
			button2.FlatAppearance.BorderColor = P.Border;
			button2.FlatAppearance.MouseOverBackColor = (accent ? P.AccentHover : P.Border);
			button2.FlatAppearance.MouseDownBackColor = (accent ? P.AccentHover : P.Border);
			return button2;
		}

		public static CheckBox Check(string text, bool on)
		{
			CheckBox checkBox = new CheckBox();
			checkBox.Text = text;
			checkBox.Checked = on;
			checkBox.AutoSize = true;
			checkBox.ForeColor = P.Fg;
			checkBox.Font = Base;
			checkBox.FlatStyle = FlatStyle.Flat;
			checkBox.Cursor = Cursors.Hand;
			checkBox.Margin = new Padding(0, S(6), 0, 0);
			CheckBox checkBox2 = checkBox;
			checkBox2.FlatAppearance.BorderColor = P.Muted;
			checkBox2.FlatAppearance.CheckedBackColor = P.Accent;
			checkBox2.FlatAppearance.MouseOverBackColor = P.Raised;
			return checkBox2;
		}

		public static TextBox Field(string text, int width)
		{
			TextBox textBox = new TextBox();
			textBox.Text = text;
			textBox.Width = S(width);
			textBox.BackColor = P.Surface;
			textBox.ForeColor = P.Fg;
			textBox.Font = Base;
			textBox.BorderStyle = BorderStyle.FixedSingle;
			textBox.Margin = new Padding(0, S(2), 0, 0);
			return textBox;
		}
	}
}
