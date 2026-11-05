using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;

namespace MonhipInstaller
{
	public class SetupForm : BaseForm
	{
		private class Step
		{
			public string Label;

			public Action<Step> Work;

			public Label View;
		}

		private readonly Options opt;

		private InstallInfo existing;

		private string dir;

		private bool desktop = true;

		public int ExitCode = 1;

		private Hardware hw;

		private PythonInfo py;

		private Python.Download pyPlan;

		private Latest latest;

		private LlamaPlan llama;

		private List<string> llamaInstalled = new List<string>();

		private ModelPlan model;

		private List<string> models = new List<string>();

		private string pyErr;

		private string latestErr;

		private string llamaErr;

		private string modelErr;

		private Cancel cancel;

		private CheckBox cbProgram;

		private CheckBox cbLlama;

		private CheckBox cbModel;

		private bool pythonInstalledNow;

		private Label statusLabel;

		private Bar bar;

		private Step current;

		public SetupForm(InstallInfo existing, Options opt)
			: base("Monhip Setup", 660, 560)
		{
			this.existing = existing;
			this.opt = opt;
			if (existing != null)
			{
				dir = existing.Dir;
				ShowManage();
				return;
			}
			dir = opt.Ziel ?? Const.DefaultDir;
			ShowWelcome();
			if (opt.Auto)
			{
				base.Shown += delegate
				{
					ShowComponents();
				};
			}
		}

		private void ShowWelcome()
		{
			Page("Monhip installieren", "");
			Body.Controls.Add(Theme.Heading("Installationsordner"));
			FlowLayoutPanel flowLayoutPanel = new FlowLayoutPanel();
			flowLayoutPanel.AutoSize = true;
			flowLayoutPanel.WrapContents = false;
			flowLayoutPanel.Margin = new Padding(0);
			FlowLayoutPanel flowLayoutPanel2 = flowLayoutPanel;
			TextBox field = Theme.Field(dir, 430);
			Button button = Theme.Button("Ändern…", false);
			button.MinimumSize = new Size(Theme.S(96), Theme.S(28));
			flowLayoutPanel2.Controls.Add(field);
			flowLayoutPanel2.Controls.Add(button);
			Body.Controls.Add(flowLayoutPanel2);
			Label free = Theme.Text("", true, 560);
			free.Margin = new Padding(0, Theme.S(6), 0, Theme.S(8));
			Body.Controls.Add(free);
			Action update = delegate
			{
				string text = "";
				try
				{
					text = Path.GetPathRoot(Path.GetFullPath(field.Text));
				}
				catch (Exception)
				{
				}
				double num = Dirs.FreeGb(field.Text);
				free.Text = "Frei auf " + text + ": " + Fmt.Gb(num);
				free.ForeColor = ((num < 25.0) ? Theme.P.Error : Theme.P.Muted);
			};
			field.TextChanged += delegate
			{
				update();
			};
			update();
			button.Click += delegate
			{
				using (FolderBrowserDialog folderBrowserDialog = new FolderBrowserDialog
				{
					Description = "Installationsordner",
					SelectedPath = field.Text
				})
				{
					if (folderBrowserDialog.ShowDialog(this) == DialogResult.OK)
					{
						field.Text = Path.Combine(folderBrowserDialog.SelectedPath, "Monhip");
					}
				}
			};
			Body.Controls.Add(Theme.Heading("Optionen"));
			CheckBox cbDesk = Theme.Check("Verknüpfung auf dem Desktop anlegen", desktop);
			Body.Controls.Add(cbDesk);
			AddButton("Abbrechen", false, delegate
			{
				Close();
			});
			AddButton("Weiter", true, delegate
			{
				string text2;
				try
				{
					text2 = Path.GetFullPath(field.Text.Trim().Trim('"'));
				}
				catch (Exception)
				{
					Ask.Info(this, "Ungültiger Pfad", field.Text);
					return;
				}
				if (Directory.Exists(text2) && Directory.EnumerateFileSystemEntries(text2).Any() && !File.Exists(Path.Combine(text2, "installation.json")) && !File.Exists(Path.Combine(text2, "Monhip.pyw")))
				{
					text2 = Path.Combine(text2, "Monhip");
				}
				dir = text2;
				desktop = cbDesk.Checked;
				existing = InstallInfo.Load(dir);
				ShowComponents();
			});
		}

		private void ShowManage()
		{
			Page("Monhip verwalten", existing.Describe());
			Label label2 = Theme.Text("Ordner: " + existing.Dir, true, 560);
			label2.Margin = new Padding(0, 0, 0, Theme.S(8));
			Body.Controls.Add(label2);
			Label status = Theme.Text("", true, 560);
			Action<string, EventHandler> action = delegate(string label, EventHandler click)
			{
				Button button = Theme.Button(label, false);
				button.MinimumSize = new Size(Theme.S(230), Theme.S(36));
				button.Margin = new Padding(0, Theme.S(6), 0, Theme.S(4));
				button.Click += click;
				Body.Controls.Add(button);
			};
			action("Nach Updates suchen", delegate
			{
				CheckUpdate(status);
			});
			action("Komponenten prüfen", delegate
			{
				ShowComponents();
			});
			action("Deinstallieren…", delegate
			{
				Program.StartUninstall(existing);
				Close();
			});
			CheckBox auto = Theme.Check("Beim Start nach Updates suchen", existing.UpdateCheck);
			auto.Margin = new Padding(0, Theme.S(16), 0, Theme.S(6));
			auto.CheckedChanged += delegate
			{
				existing.UpdateCheck = auto.Checked;
				existing.Save();
			};
			Body.Controls.Add(auto);
			Body.Controls.Add(status);
			AddButton("Schließen", false, delegate
			{
				Close();
			});
			AddButton("Monhip starten", true, delegate
			{
				if (Launcher.Start(existing, this))
				{
					Close();
				}
			});
		}

		private void CheckUpdate(Label status)
		{
			status.Text = "Prüfe …";
			InstallInfo info = existing;
			Thread thread = new Thread((ThreadStart)delegate
			{
				Latest upd = null;
				string err = null;
				try
				{
					upd = GitHub.CheckUpdate(info, 20000);
				}
				catch (Exception ex)
				{
					err = ex.Message;
				}
				Ui(delegate
				{
					if (err != null)
					{
						status.Text = "Fehler: " + err;
					}
					else if (upd == null)
					{
						status.Text = "Aktuell (" + info.Label + ")";
					}
					else
					{
						status.Text = "Update verfügbar: " + upd.Label;
						string text = ((upd.Notes.Count > 0) ? ("\n\n" + string.Join("\n", upd.Notes.Select((string n) => "• " + n))) : "");
						if (Ask.Show(this, "Update verfügbar", upd.Label + " (" + Fmt.Date(upd.Date) + ")" + text, "Aktualisieren", "Später") && WaitUntilClosed())
						{
							latest = upd;
							Run(new List<Step> { ProgramStep(false, true) });
						}
					}
				});
			});
			thread.IsBackground = true;
			thread.Start();
		}

		private bool WaitUntilClosed()
		{
			while (Running.InDir(dir).Count > 0)
			{
				if (!Ask.Show(this, "Monhip läuft", "Zum Fortfahren beenden.", "Erneut prüfen", "Abbrechen"))
				{
					return false;
				}
			}
			return true;
		}

		private void ShowComponents()
		{
			Page((existing == null) ? "Installationsoptionen" : "Komponenten prüfen", "");
			Body.Controls.Add(Theme.Text("Prüfe Komponenten …", true, 560));
			Bar bar = new Bar();
			bar.Width = Theme.S(560);
			bar.Value = -1.0;
			Bar value = bar;
			Body.Controls.Add(value);
			AddButton("Abbrechen", false, delegate
			{
				Close();
			});
			Thread thread = new Thread((ThreadStart)delegate
			{
				Probe();
				Ui(ShowChoices);
			});
			thread.IsBackground = true;
			thread.Start();
		}

		private void Probe()
		{
			hw = Hw.Detect();
			py = Python.Find();
			pyPlan = null;
			pyErr = (latestErr = (llamaErr = (modelErr = null)));
			llama = null;
			model = null;
			latest = null;
			if (py == null)
			{
				try
				{
					pyPlan = Python.Plan();
				}
				catch (Exception ex)
				{
					pyErr = ex.Message;
				}
			}
			try
			{
				if (opt.Quelle != null)
				{
					latest = new Latest
					{
						Label = "lokal",
						Date = DateTime.Now.ToString("yyyy-MM-dd"),
						Source = "lokal",
						Zip = Path.GetFullPath(opt.Quelle)
					};
				}
				else
				{
					latest = GitHub.Get((existing != null) ? existing.Repo : "defectengineerkristian/monhip", (existing != null) ? existing.Branch : "", 20000);
				}
			}
			catch (Exception ex2)
			{
				latestErr = ex2.Message;
			}
			llamaInstalled = Llama.Installed(dir);
			if (llamaInstalled.Count == 0)
			{
				try
				{
					llama = Llama.Plan(dir, hw);
				}
				catch (Exception ex3)
				{
					llamaErr = ex3.Message;
				}
			}
			models = Model.Existing(dir);
			if (!File.Exists(Model.Target(dir)))
			{
				try
				{
					model = Model.Plan(dir);
				}
				catch (Exception ex4)
				{
					modelErr = ex4.Message;
				}
			}
		}

		private void ShowChoices()
		{
			bool fresh = existing == null;
			Page(fresh ? "Installationsoptionen" : "Komponenten prüfen", fresh ? "" : existing.Describe());
			bool blocked = false;
			if (py != null)
			{
				Row(Disabled(Theme.Check("Python " + py.Version, false)), "Installiert: " + py.Exe, false);
			}
			else if (pyPlan != null)
			{
				Row(Disabled(Theme.Check("Python " + pyPlan.Version, true)), "python.org · " + Fmt.Size(pyPlan.Size), false);
			}
			else
			{
				Row(Disabled(Theme.Check("Python", false)), "python.org nicht erreichbar: " + pyErr, true);
				blocked = true;
			}
			if (latest != null)
			{
				bool flag = fresh || latest.Sha != existing.Version || opt.Quelle != null;
				cbProgram = Theme.Check(fresh ? ("Monhip " + latest.Label) : "Programmdateien neu laden", fresh || flag);
				if (fresh)
				{
					Disabled(cbProgram);
				}
				Row(cbProgram, fresh ? ("github.com/defectengineerkristian/monhip · " + Fmt.Date(latest.Date)) : (flag ? ("Neue Version: " + latest.Label + " (" + Fmt.Date(latest.Date) + ")") : ("Aktuell: " + existing.Label)), false);
			}
			else
			{
				cbProgram = Disabled(Theme.Check("Monhip", false));
				Row(cbProgram, "GitHub nicht erreichbar: " + latestErr, true);
				if (fresh)
				{
					blocked = true;
				}
			}
			if (llamaInstalled.Count > 0)
			{
				cbLlama = Row(Disabled(Theme.Check("llama.cpp", false)), "Installiert: " + Llama.Label(llamaInstalled[0]), false);
			}
			else if (llama != null)
			{
				cbLlama = Row(Theme.Check("llama.cpp", !opt.NurProgramm), llama.Tag + " · " + llama.Kind + " · " + Fmt.Size(llama.Size), false);
			}
			else
			{
				cbLlama = Row(Disabled(Theme.Check("llama.cpp", false)), "GitHub nicht erreichbar: " + llamaErr, true);
			}
			double num = Dirs.FreeGb(dir);
			string text = "Qwen3.8-27B Q4_K_M + mmproj";
			List<string> list = models.Where((string m) => !string.Equals(m, Model.Target(dir), StringComparison.OrdinalIgnoreCase)).ToList();
			if (File.Exists(Model.Target(dir)))
			{
				cbModel = Row(Disabled(Theme.Check(text, false)), "Vorhanden", false);
			}
			else if (model != null)
			{
				double num2 = (double)(model.Size - model.Have) / 1073741824.0;
				string text2 = "unsloth/Qwen3.8-27B-GGUF · " + Fmt.Size(model.Size);
				if (model.Have > 0)
				{
					text2 = text2 + " · " + Fmt.Size(model.Have) + " bereits geladen";
				}
				if (list.Count > 0)
				{
					object obj = text2;
					text2 = string.Concat(obj, " · ", list.Count, " weitere(s) Modell(e) vorhanden");
				}
				cbModel = Row(Theme.Check(text, list.Count == 0 && !opt.NurProgramm), text2, false);
				if (num < num2 + 2.0)
				{
					Disabled(cbModel).Checked = false;
					Warn("Zu wenig Speicherplatz: " + Fmt.Gb(num2 + 2.0) + " benötigt, " + Fmt.Gb(num) + " frei");
				}
				else if (hw.RamGb + hw.VramGb < 20.0)
				{
					Warn("RAM + VRAM " + Fmt.Gb(hw.RamGb + hw.VramGb) + " (empfohlen ab " + 20.0 + " GB)");
				}
			}
			else
			{
				cbModel = Row(Disabled(Theme.Check(text, false)), "Hugging Face nicht erreichbar: " + modelErr, true);
			}
			Label label = Theme.Text(hw.Gpu + " · VRAM " + Fmt.Gb(hw.VramGb) + " · RAM " + Fmt.Gb(hw.RamGb) + " · frei " + Fmt.Gb(num), true, 560);
			label.Margin = new Padding(0, Theme.S(14), 0, 0);
			Body.Controls.Add(label);
			AddButton("Abbrechen", false, delegate
			{
				Close();
			});
			if (fresh)
			{
				AddButton("Zurück", false, delegate
				{
					ShowWelcome();
				});
			}
			else
			{
				AddButton("Zurück", false, delegate
				{
					ShowManage();
				});
			}
			Button go = AddButton(fresh ? "Installieren" : "Ausführen", true, delegate
			{
				Start();
			});
			Action refresh = delegate
			{
				go.Enabled = !blocked && (fresh || py == null || cbProgram.Checked || cbLlama.Checked || cbModel.Checked);
			};
			CheckBox[] array = new CheckBox[3] { cbProgram, cbLlama, cbModel };
			foreach (CheckBox checkBox in array)
			{
				checkBox.CheckedChanged += delegate
				{
					refresh();
				};
			}
			refresh();
			if (opt.Auto && go.Enabled)
			{
				BeginInvoke(new Action(Start));
			}
		}

		private CheckBox Row(CheckBox cb, string detail, bool error)
		{
			Body.Controls.Add(cb);
			Label label = Theme.Text(detail, true, 530);
			label.Margin = new Padding(Theme.S(22), 0, 0, Theme.S(4));
			if (error)
			{
				label.ForeColor = Theme.P.Error;
			}
			Body.Controls.Add(label);
			return cb;
		}

		private static CheckBox Disabled(CheckBox cb)
		{
			cb.Enabled = false;
			return cb;
		}

		private void Warn(string text)
		{
			Label label = Theme.Text(text, true, 530);
			label.ForeColor = Theme.P.Error;
			label.Margin = new Padding(Theme.S(22), 0, 0, Theme.S(4));
			Body.Controls.Add(label);
		}

		private void Start()
		{
			bool flag = existing == null;
			if (!flag && cbProgram.Checked && !WaitUntilClosed())
			{
				return;
			}
			List<Step> list = new List<Step>();
			if (py == null && pyPlan != null)
			{
				list.Add(new Step
				{
					Label = "Python " + pyPlan.Version,
					Work = PythonStep
				});
			}
			if (flag || cbProgram.Checked || py == null)
			{
				list.Add(ProgramStep(flag, flag || cbProgram.Checked));
			}
			if (cbLlama.Checked && llama != null)
			{
				list.Add(new Step
				{
					Label = "llama.cpp " + llama.Tag + " · " + llama.Kind,
					Work = delegate(Step s)
					{
						Llama.Install(llama, Progress(s, "llama.cpp"), cancel);
					}
				});
			}
			if (cbModel.Checked && model != null)
			{
				list.Add(new Step
				{
					Label = "Qwen3.8-27B Q4_K_M · " + Fmt.Size(model.Size),
					Work = delegate(Step s)
					{
						Model.Install(model, Progress(s, "Qwen3.8-27B"), cancel);
					}
				});
			}
			Run(list);
		}

		private void PythonStep(Step s)
		{
			Python.Install(pyPlan, Progress(s, "Python"), cancel, delegate(string t)
			{
				Status(t, -1.0);
			});
			py = Python.Find();
			if (py == null)
			{
				throw new Exception("Python nach der Installation nicht gefunden – Neustart erforderlich.");
			}
			pythonInstalledNow = true;
		}

		private Step ProgramStep(bool fresh, bool download)
		{
			Step step = new Step();
			step.Label = (fresh ? "Monhip" : (download ? "Programmdateien" : "Konfiguration"));
			step.Work = delegate(Step s)
			{
				InstallInfo installInfo = existing ?? new InstallInfo
				{
					Dir = dir,
					Installed = DateTime.Now.ToString("yyyy-MM-dd HH:mm")
				};
				if (download)
				{
					ProgramFiles.Install(installInfo, latest, Progress(s, "Monhip"), cancel);
				}
				string fullPath = Path.GetFullPath(Application.ExecutablePath);
				if (!string.Equals(fullPath, installInfo.Launcher, StringComparison.OrdinalIgnoreCase))
				{
					File.Copy(fullPath, installInfo.Launcher, true);
				}
				if (py != null)
				{
					installInfo.Python = py.Pythonw;
					if (pythonInstalledNow || !installInfo.PythonBySetup)
					{
						installInfo.PythonVersion = py.Version.ToString();
					}
					installInfo.PythonBySetup = installInfo.PythonBySetup || pythonInstalledNow;
				}
				if (fresh && !opt.OhneVerknuepfungen)
				{
					Status("Verknüpfungen, Apps-Eintrag …", -1.0);
					List<string> list = new List<string>
					{
						Shell.StartMenu("Monhip"),
						Shell.StartMenu("Monhip verwalten")
					};
					Shell.Shortcut(list[0], installInfo.Launcher, "", installInfo.Dir, "Monhip");
					Shell.Shortcut(list[1], installInfo.Launcher, "--verwalten", installInfo.Dir, "Monhip verwalten");
					if (desktop)
					{
						list.Add(Shell.Desktop("Monhip"));
						Shell.Shortcut(list[2], installInfo.Launcher, "", installInfo.Dir, "Monhip");
					}
					installInfo.Shortcuts = list;
				}
				installInfo.Save();
				if (!opt.OhneVerknuepfungen)
				{
					if (fresh)
					{
						Shell.WriteAppsEntry(installInfo);
					}
					else
					{
						Shell.UpdateAppsVersion(installInfo);
					}
				}
				existing = installInfo;
			};
			return step;
		}

		private void Status(string text, double pct)
		{
			Ui(delegate
			{
				statusLabel.Text = text;
				bar.Value = pct;
			});
		}

		private ProgressFn Progress(Step s, string name)
		{
			Speed speed = new Speed();
			return delegate(long done, long total)
			{
				Status(speed.Text(name, done, total), (total > 0) ? ((double)done * 100.0 / (double)total) : (-1.0));
			};
		}

		private void Run(List<Step> steps)
		{
			cancel = new Cancel();
			Page("Installation", "");
			foreach (Step step in steps)
			{
				step.View = Theme.Text("○   " + step.Label, false, 560);
				step.View.ForeColor = Theme.P.Muted;
				step.View.Margin = new Padding(0, Theme.S(4), 0, Theme.S(4));
				Body.Controls.Add(step.View);
			}
			bar = new Bar
			{
				Width = Theme.S(560),
				Value = -1.0
			};
			Body.Controls.Add(bar);
			statusLabel = Theme.Text("", true, 560);
			Body.Controls.Add(statusLabel);
			Button stop = null;
			stop = AddButton("Abbrechen", false, delegate
			{
				cancel.Set();
				stop.Enabled = false;
			});
			Thread thread = new Thread((ThreadStart)delegate
			{
				string error = null;
				foreach (Step s in steps)
				{
					current = s;
					SetupForm setupForm = this;
					Action a = delegate
					{
						s.View.Text = "●   " + s.Label;
						s.View.ForeColor = Theme.P.Fg;
						s.View.Font = Theme.Bold;
					};
					setupForm.Ui(a);
					Status("", -1.0);
					try
					{
						s.Work(s);
						Ui(delegate
						{
							s.View.Text = "✔   " + s.Label;
							s.View.ForeColor = Theme.P.Ok;
							s.View.Font = Theme.Base;
						});
					}
					catch (Exception ex)
					{
						error = (cancel.IsSet ? "" : ex.Message);
						Ui(delegate
						{
							s.View.Text = "✖   " + s.Label;
							s.View.ForeColor = Theme.P.Error;
							s.View.Font = Theme.Base;
						});
						break;
					}
				}
				Ui(delegate
				{
					ShowDone(error);
				});
			});
			thread.IsBackground = true;
			thread.Start();
		}

		private void ShowDone(string error)
		{
			if (error == null)
			{
				ExitCode = 0;
				Page("Installation abgeschlossen", "");
				bool flag = existing != null && File.Exists(existing.Pyw);
				CheckBox run = Theme.Check("Monhip starten", flag && !opt.Auto);
				run.Enabled = flag;
				run.Margin = new Padding(0, Theme.S(14), 0, 0);
				Body.Controls.Add(run);
				AddButton("Fertigstellen", true, delegate
				{
					if (run.Checked)
					{
						Launcher.Start(existing, this);
					}
					Close();
				});
			}
			else
			{
				Page((error == "") ? "Abgebrochen" : "Fehler", "");
				if (error != "")
				{
					Body.Controls.Add(Theme.Text(error, false, 560));
				}
				AddButton("Schließen", false, delegate
				{
					Close();
				});
				AddButton("Erneut versuchen", true, delegate
				{
					ShowComponents();
				});
			}
			if (opt.Auto)
			{
				BeginInvoke(new Action(base.Close));
			}
		}
	}
}
