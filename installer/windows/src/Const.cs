using System;
using System.IO;
using System.Linq;

namespace MonhipInstaller
{
	public static class Const
	{
		public const string Repo = "defectengineerkristian/monhip";

		public const string LauncherExe = "Monhip.exe";

		public const string UninstallKey = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Monhip";

		public const string PythonSeries = "3.13";

		public const string UserAgent = "Monhip-Installer";

		public static readonly Version MinPython = new Version(3, 13);

		// Daten von Monhip und vom Installer: ein Update ersetzt sie nie, auch wenn das Paket einen gleichnamigen Eintrag
		// hätte (Monhip legt sie neben Monhip.pyw an – siehe app/plattform.py, DATA_DIR)
		public static readonly string[] Protected = new string[]
		{
			"config.json", "chats", "modelle", "server", "raeume", "checkpoints", "sicherungen", "gedaechtnis.json",
			"erinnerungen.json", "installation.json", "_update", ".git", "Monhip.exe", "Monhip-Setup.exe"
		};

		public static string DefaultDir
		{
			get
			{
				return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Monhip");
			}
		}

		public static bool IsProtected(string name)
		{
			return Protected.Any((string p) => string.Equals(p, name, StringComparison.OrdinalIgnoreCase));
		}
	}
}
