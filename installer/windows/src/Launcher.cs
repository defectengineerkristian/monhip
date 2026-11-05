using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Windows.Forms;

namespace MonhipInstaller
{
	public static class Launcher
	{
		public static int Run(InstallInfo info)
		{
			if (info.UpdateCheck && Running.InDir(info.Dir).Count == 0)
			{
				Latest[] box = new Latest[1];
				Thread thread = new Thread((ThreadStart)delegate
				{
					try
					{
						box[0] = GitHub.CheckUpdate(info, 5000);
					}
					catch (Exception)
					{
					}
				});
				thread.IsBackground = true;
				thread.Start();
				if (thread.Join(6000) && box[0] != null)
				{
					using (UpdateForm mainForm = new UpdateForm(info, box[0]))
					{
						Application.Run(mainForm);
					}
				}
			}
			if (!Start(info, null))
			{
				return 1;
			}
			return 0;
		}

		public static bool Start(InstallInfo info, IWin32Window owner)
		{
			string python = info.Python;
			if (string.IsNullOrEmpty(python) || !File.Exists(python))
			{
				PythonInfo pythonInfo = Python.Find();
				if (pythonInfo != null)
				{
					info.Python = pythonInfo.Pythonw;
					try
					{
						info.Save();
					}
					catch (Exception)
					{
					}
					python = info.Python;
				}
			}
			if (string.IsNullOrEmpty(python) || !File.Exists(python))
			{
				Ask.Info(owner, "Python nicht gefunden", "Python 3.13 erforderlich – Monhip verwalten → Komponenten prüfen.");
				return false;
			}
			if (!File.Exists(info.Pyw))
			{
				Ask.Info(owner, "Programmdateien fehlen", "Monhip.pyw fehlt in " + info.Dir + ".");
				return false;
			}
			ProcessStartInfo processStartInfo = new ProcessStartInfo(python, Fmt.Quote(info.Pyw));
			processStartInfo.WorkingDirectory = info.Dir;
			processStartInfo.UseShellExecute = false;
			Process.Start(processStartInfo);
			return true;
		}
	}
}
