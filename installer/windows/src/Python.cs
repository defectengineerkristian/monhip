using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace MonhipInstaller
{
	public static class Python
	{
		public class Download
		{
			public string Version;

			public string Url;

			public long Size;
		}

		public static PythonInfo Find()
		{
			List<string[]> list = new List<string[]>();
			RegistryKey[] array = new RegistryKey[2]
			{
				Registry.CurrentUser,
				Registry.LocalMachine
			};
			foreach (RegistryKey registryKey in array)
			{
				string[] array2 = new string[2] { "Software\\Python\\PythonCore", "Software\\WOW6432Node\\Python\\PythonCore" };
				foreach (string name in array2)
				{
					try
					{
						using (RegistryKey registryKey2 = registryKey.OpenSubKey(name))
						{
							if (registryKey2 == null)
							{
								continue;
							}
							string[] subKeyNames = registryKey2.GetSubKeyNames();
							foreach (string text in subKeyNames)
							{
								using (RegistryKey registryKey3 = registryKey2.OpenSubKey(text + "\\InstallPath"))
								{
									if (registryKey3 != null)
									{
										string text2 = registryKey3.GetValue("ExecutablePath") as string;
										string text3 = registryKey3.GetValue("") as string;
										if (string.IsNullOrEmpty(text2) && text3 != null)
										{
											text2 = Path.Combine(text3, "python.exe");
										}
										if (!string.IsNullOrEmpty(text2) && File.Exists(text2))
										{
											list.Add(new string[1] { text2 });
										}
									}
								}
							}
						}
					}
					catch (Exception)
					{
					}
				}
			}
			list.Add(new string[2] { "py.exe", "-3" });
			string[] array3 = (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';');
			foreach (string text4 in array3)
			{
				try
				{
					string text5 = Path.Combine(text4.Trim().Trim('"'), "python.exe");
					if (File.Exists(text5) && text5.IndexOf("\\WindowsApps\\", StringComparison.OrdinalIgnoreCase) < 0)
					{
						list.Add(new string[1] { text5 });
					}
				}
				catch (ArgumentException)
				{
				}
			}
			string[] array4 = new string[2]
			{
				Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Python"),
				Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles)
			};
			foreach (string path in array4)
			{
				try
				{
					if (!Directory.Exists(path))
					{
						continue;
					}
					string[] directories = Directory.GetDirectories(path, "Python3*");
					foreach (string path2 in directories)
					{
						if (File.Exists(Path.Combine(path2, "python.exe")))
						{
							list.Add(new string[1] { Path.Combine(path2, "python.exe") });
						}
					}
				}
				catch (Exception)
				{
				}
			}
			PythonInfo pythonInfo = null;
			HashSet<string> hashSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
			foreach (string[] item in list)
			{
				if (hashSet.Add(string.Join(" ", item)))
				{
					PythonInfo pythonInfo2 = Probe(item);
					if (pythonInfo2 != null && pythonInfo2.Version >= Const.MinPython && (pythonInfo == null || pythonInfo2.Version > pythonInfo.Version))
					{
						pythonInfo = pythonInfo2;
					}
				}
			}
			return pythonInfo;
		}

		private static PythonInfo Probe(string[] cand)
		{
			string text = "-c \"import sys, tkinter; print(*sys.version_info[:3], sep=chr(46)); print(sys.executable)\"";
			ProcessStartInfo processStartInfo = new ProcessStartInfo(cand[0], ((cand.Length > 1) ? (cand[1] + " ") : "") + text);
			processStartInfo.UseShellExecute = false;
			processStartInfo.RedirectStandardOutput = true;
			processStartInfo.CreateNoWindow = true;
			try
			{
				using (Process process = Process.Start(processStartInfo))
				{
					string text2 = process.StandardOutput.ReadToEnd();
					process.WaitForExit(15000);
					if (!process.HasExited || process.ExitCode != 0)
					{
						return null;
					}
					string[] array = text2.Split(new char[2] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
					Version result;
					if (array.Length >= 2 && Version.TryParse(array[0].Trim(), out result) && File.Exists(array[1].Trim()))
					{
						PythonInfo pythonInfo = new PythonInfo();
						pythonInfo.Version = result;
						pythonInfo.Exe = array[1].Trim();
						return pythonInfo;
					}
				}
			}
			catch (Exception)
			{
			}
			return null;
		}

		public static Download Plan()
		{
			string arg = (Dirs.IsArm64 ? "arm64" : "amd64");
			string @string = Http.GetString("https://www.python.org/ftp/python/", 30000, false);
			IOrderedEnumerable<Version> orderedEnumerable = from v in (from Match m in Regex.Matches(@string, "href=\"(" + Regex.Escape("3.13") + "\\.\\d+)/\"")
					select new Version(m.Groups[1].Value)).Distinct()
				orderby v descending
				select v;
			foreach (Version item in orderedEnumerable)
			{
				string url = string.Format("https://www.python.org/ftp/python/{0}/python-{0}-{1}.exe", item, arg);
				try
				{
					Download download = new Download();
					download.Version = item.ToString();
					download.Url = url;
					download.Size = Http.HeadSize(url);
					return download;
				}
				catch (WebException)
				{
				}
			}
			throw new Exception("Kein Windows-Installer für Python 3.13 auf python.org.");
		}

		public static void Install(Download d, ProgressFn progress, Cancel cancel, Action<string> status)
		{
			string text = Path.Combine(Path.GetTempPath(), "python-" + d.Version + "-setup.exe");
			Http.Download(d.Url, text, 0L, d.Size, false, progress, cancel);
			status("Installiere Python " + d.Version + " …");
			ProcessStartInfo processStartInfo = new ProcessStartInfo(text, "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0 Include_doc=0 Shortcuts=0");
			processStartInfo.UseShellExecute = false;
			using (Process process = Process.Start(processStartInfo))
			{
				process.WaitForExit();
				try
				{
					File.Delete(text);
				}
				catch (Exception)
				{
				}
				if (process.ExitCode != 0 && process.ExitCode != 3010)
				{
					throw new Exception("Python-Installation fehlgeschlagen (Code " + process.ExitCode + ").");
				}
			}
		}

		public static string[] Uninstaller(InstallInfo info)
		{
			if (info == null || !info.PythonBySetup || info.PythonVersion == "")
			{
				return null;
			}
			try
			{
				using (RegistryKey registryKey = Registry.CurrentUser.OpenSubKey("Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"))
				{
					if (registryKey == null)
					{
						return null;
					}
					string[] subKeyNames = registryKey.GetSubKeyNames();
					foreach (string name in subKeyNames)
					{
						using (RegistryKey registryKey2 = registryKey.OpenSubKey(name))
						{
							string text = ((registryKey2 == null) ? null : (registryKey2.GetValue("DisplayName") as string));
							string text2 = ((registryKey2 == null) ? null : (registryKey2.GetValue("QuietUninstallString") as string));
							if (text != null && text2 != null && text.StartsWith("Python " + info.PythonVersion + " "))
							{
								Match match = Regex.Match(text2, "^\\s*\"([^\"]+)\"\\s*(.*)$");
								if (match.Success)
								{
									return new string[2]
									{
										match.Groups[1].Value,
										match.Groups[2].Value
									};
								}
							}
						}
					}
				}
			}
			catch (Exception)
			{
			}
			return null;
		}
	}
}
