using System;
using System.Drawing;
using System.Windows.Forms;

namespace MonhipInstaller
{
	public class Ask : BaseForm
	{
		private Ask(string caption, string title, string text, string yes, string no)
			: base(caption, 520, 260)
		{
			Page(title, "");
			Label l = Theme.Text(text, false, 460);
			Body.Controls.Add(l);
			if (no != null)
			{
				AddButton(no, false, delegate
				{
					base.DialogResult = DialogResult.No;
					Close();
				});
			}
			AddButton(yes, true, delegate
			{
				base.DialogResult = DialogResult.Yes;
				Close();
			});
			base.StartPosition = FormStartPosition.CenterParent;
			base.Load += delegate
			{
				int num = l.PreferredHeight + Theme.S(178);
				if (num > base.ClientSize.Height)
				{
					base.ClientSize = new Size(base.ClientSize.Width, Math.Min(num, Theme.S(620)));
				}
			};
		}

		public static bool Show(IWin32Window owner, string title, string text, string yes, string no)
		{
			using (Ask ask = new Ask("Monhip", title, text, yes, no))
			{
				if (owner == null)
				{
					ask.StartPosition = FormStartPosition.CenterScreen;
				}
				return ask.ShowDialog(owner) == DialogResult.Yes;
			}
		}

		public static void Info(IWin32Window owner, string title, string text)
		{
			Show(owner, title, text, "OK", null);
		}
	}
}
