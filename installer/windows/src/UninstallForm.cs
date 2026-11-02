using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Windows.Forms;

namespace MonhipInstaller
{
	public class UninstallForm : BaseForm
	{
		private readonly InstallInfo info;

		private readonly List<Part> parts;

		private readonly Dictionary<Part, CheckBox> boxes = new Dictionary<Part, CheckBox>();

		public UninstallForm(InstallInfo info, bool preselect)
			: base("Monhip deinstallieren", 620, 540)
		{
			this.info = info;
			parts = Uninstall.Parts(info);
			Page("Monhip deinstallieren", "Auswahl wird endgültig gelöscht.");
			foreach (Part part in parts)
			{
				CheckBox value = Theme.Check(part.Label, preselect);
				boxes[part] = value;
				Body.Controls.Add(value);
			}
			Part py = parts.FirstOrDefault((Part p) => p.Key == "python");
			Part prog = parts.First((Part p) => p.Key == "program");
			if (py != null)
			{
				boxes[py].CheckedChanged += delegate
				{
					if (boxes[py].Checked)
					{
						boxes[prog].Checked = true;
					}
				};
			}
			Button button = Theme.Button("Alles auswählen", false);
			button.Margin = new Padding(0, Theme.S(12), 0, 0);
			button.Click += delegate
			{
				foreach (CheckBox value2 in boxes.Values)
				{
					value2.Checked = true;
				}
			};
			Body.Controls.Add(button);
			AddButton("Abbrechen", false, delegate
			{
				Close();
			});
			AddButton("Entfernen…", true, delegate
			{
				Remove();
			});
			Thread thread = new Thread((ThreadStart)delegate
			{
				Uninstall.Measure(parts);
				Ui(delegate
				{
					foreach (Part part2 in parts)
					{
						boxes[part2].Text = part2.Label + ((part2.Size > 0) ? ("  ·  " + Fmt.Size(part2.Size)) : "");
					}
				});
			});
			thread.IsBackground = true;
			thread.Start();
		}

		private void Remove()
		{
			List<Part> chosen = parts.Where((Part p) => boxes[p].Checked).ToList();
			if (chosen.Count == 0 || !Ask.Show(this, "Endgültig löschen?", string.Join("\n", chosen.Select((Part p) => "•  " + p.Label)), "Löschen", "Abbrechen"))
			{
				return;
			}
			while (Running.InDir(info.Dir).Count > 0)
			{
				if (!Ask.Show(this, "Monhip läuft", "Zum Fortfahren beenden.", "Erneut prüfen", "Abbrechen"))
				{
					return;
				}
			}
			Page("Deinstallation", "");
			Bar bar = new Bar();
			bar.Width = Theme.S(560);
			bar.Value = -1.0;
			Bar value = bar;
			Body.Controls.Add(value);
			Label status = Theme.Text("", true, 560);
			Body.Controls.Add(status);
			Thread thread = new Thread((ThreadStart)delegate
			{
				List<string> rest = null;
				string err = null;
				try
				{
					rest = Uninstall.Remove(info, chosen, delegate(string t)
					{
						Ui(delegate
						{
							status.Text = t;
						});
					});
				}
				catch (Exception ex)
				{
					err = ex.Message;
				}
				Ui(delegate
				{
					Done(rest, err);
				});
			});
			thread.IsBackground = true;
			thread.Start();
		}

		private void Done(List<string> rest, string err)
		{
			Page((err != null) ? "Unvollständig" : "Deinstallation abgeschlossen", "");
			if (err != null)
			{
				Body.Controls.Add(Theme.Text(err, false, 560));
			}
			if (rest != null && rest.Count > 0)
			{
				Body.Controls.Add(Theme.Text("Verblieben in " + info.Dir + ":\n" + string.Join("\n", rest.Select((string r) => "•  " + r)), false, 560));
			}
			AddButton("Schließen", true, delegate
			{
				Close();
			});
		}
	}
}
