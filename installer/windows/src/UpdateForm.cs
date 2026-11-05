using System;
using System.Linq;
using System.Threading;
using System.Windows.Forms;

namespace MonhipInstaller
{
	public class UpdateForm : BaseForm
	{
		private readonly InstallInfo info;

		private readonly Latest upd;

		public UpdateForm(InstallInfo info, Latest upd)
			: base("Monhip – Update", 560, 420)
		{
			UpdateForm updateForm = this;
			this.info = info;
			this.upd = upd;
			Page("Update verfügbar", upd.Label + " (" + Fmt.Date(upd.Date) + ")" + ((info.Label == "") ? "" : (" · installiert: " + info.Label)));
			if (upd.Notes.Count > 0)
			{
				Body.Controls.Add(Theme.Heading("Änderungen"));
				foreach (string item in upd.Notes.Take(10))
				{
					Body.Controls.Add(Theme.Text("•  " + item, false, 480));
				}
			}
			CheckBox never = Theme.Check("Nicht mehr nach Updates suchen", false);
			never.Margin = new Padding(0, Theme.S(12), 0, 0);
			Body.Controls.Add(never);
			AddButton("Später", false, delegate
			{
				if (never.Checked)
				{
					info.UpdateCheck = false;
					try
					{
						info.Save();
					}
					catch (Exception)
					{
					}
				}
				updateForm.Close();
			});
			AddButton("Aktualisieren", true, delegate
			{
				Install();
			});
		}

		private void Install()
		{
			Page("Update", upd.Label);
			Bar bar = new Bar
			{
				Width = Theme.S(480),
				Value = -1.0
			};
			Body.Controls.Add(bar);
			Label status = Theme.Text("Lade …", true, 480);
			Body.Controls.Add(status);
			Cancel cancel = new Cancel();
			Thread thread = new Thread((ThreadStart)delegate
			{
				string err = null;
				try
				{
					ProgramFiles.Install(info, upd, delegate(long d, long n)
					{
						Ui(delegate
						{
							status.Text = "Lade … " + Fmt.Size(d) + ((n > 0) ? (" von " + Fmt.Size(n)) : "");
							bar.Value = ((n > 0) ? ((double)d * 100.0 / (double)n) : (-1.0));
						});
					}, cancel);
					info.Save();
					Shell.UpdateAppsVersion(info);
				}
				catch (Exception ex)
				{
					err = ex.Message;
				}
				Ui(delegate
				{
					if (err != null)
					{
						Ask.Info(this, "Update fehlgeschlagen", err);
					}
					Close();
				});
			});
			thread.IsBackground = true;
			thread.Start();
		}
	}
}
