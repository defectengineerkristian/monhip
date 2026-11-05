using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Windows.Forms;

namespace MonhipInstaller
{
	public static class Program
	{
		[STAThread]
		private static int Main(string[] args)
		{
			ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
			Application.EnableVisualStyles();
			Application.SetCompatibleTextRenderingDefault(false);
			Options options = Options.Parse(args);
			string fullPath = Path.GetFullPath(Application.ExecutablePath);
			InstallInfo installInfo = InstallInfo.Load(Path.GetDirectoryName(fullPath));
			if (options.Uninstall)
			{
				InstallInfo installInfo2 = ((options.Ordner != null) ? InstallInfo.Load(options.Ordner) : (installInfo ?? InstallInfo.FindRegistered()));
				if (installInfo2 == null)
				{
					Theme.Init(null);
					Ask.Info(null, "Keine Installation gefunden", "");
					return 1;
				}
				if (options.Ordner == null && Inside(fullPath, installInfo2.Dir))
				{
					StartUninstall(installInfo2);
					return 0;
				}
				Theme.Init(installInfo2.Dir);
				Application.Run(new UninstallForm(installInfo2, true));
				if (options.Ordner != null)
				{
					DeleteSelfLater(fullPath);
				}
				return 0;
			}
			if (installInfo != null && !options.Manage)
			{
				Theme.Init(installInfo.Dir);
				return Launcher.Run(installInfo);
			}
			InstallInfo installInfo3 = installInfo ?? ((options.Ziel != null) ? InstallInfo.Load(options.Ziel) : InstallInfo.FindRegistered());
			Theme.Init((installInfo3 != null) ? installInfo3.Dir : null);
			using (SetupForm setupForm = new SetupForm(installInfo3, options))
			{
				Application.Run(setupForm);
				return setupForm.ExitCode;
			}
		}

		private static bool Inside(string file, string dir)
		{
			return file.StartsWith(Path.GetFullPath(dir).TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
		}

		public static void StartUninstall(InstallInfo info)
		{
			string text = Path.Combine(Path.GetTempPath(), "Monhip-Deinstallation.exe");
			try
			{
				File.Copy(Application.ExecutablePath, text, true);
			}
			catch (IOException)
			{
				text = Path.Combine(Path.GetTempPath(), "Monhip-Deinstallation-" + Guid.NewGuid().ToString("N").Substring(0, 6) + ".exe");
				File.Copy(Application.ExecutablePath, text, true);
			}
			ProcessStartInfo processStartInfo = new ProcessStartInfo(text, "--deinstallieren --ordner " + Fmt.Quote(info.Dir));
			processStartInfo.UseShellExecute = false;
			processStartInfo.WorkingDirectory = Path.GetTempPath();
			Process.Start(processStartInfo);
		}

		private static void DeleteSelfLater(string self)
		{
			ProcessStartInfo processStartInfo = new ProcessStartInfo("cmd.exe", "/c ping 127.0.0.1 -n 3 >nul & del /f /q " + Fmt.Quote(self));
			processStartInfo.CreateNoWindow = true;
			processStartInfo.UseShellExecute = false;
			processStartInfo.WindowStyle = ProcessWindowStyle.Hidden;
			processStartInfo.WorkingDirectory = Path.GetTempPath();
			Process.Start(processStartInfo);
		}
	}
}
